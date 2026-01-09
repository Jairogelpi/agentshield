# agentshield_core/app/db.py
import os
import json
import uuid
from supabase import create_client, Client
import redis
import asyncio
import logging
import time

logger = logging.getLogger("agentshield.db")

# Configuración
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
REDIS_URL = os.getenv("REDIS_URL")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Nombre de la cola de seguridad (WAL)
WAL_QUEUE_KEY = "wal:pending_charges"

async def get_current_spend(tenant_id: str, cost_center: str):
    """Lectura optimista desde Redis con Fallback a DB"""
    key = f"spend:{tenant_id}:{cost_center}"
    spend = redis_client.get(key)
    if spend: return float(spend)
    
    loop = asyncio.get_running_loop()
    def _fetch():
        return supabase.table("cost_centers").select("current_spend").eq("tenant_id", tenant_id).eq("id", cost_center).execute()
    
    res = await loop.run_in_executor(None, _fetch)
    if res.data:
        val = res.data[0]['current_spend']
        redis_client.set(key, val)
        return float(val)
    return 0.0

async def increment_spend(tenant_id: str, cost_center: str, amount: float):
    """
    1. Actualiza Redis (Velocidad).
    2. Escribe en WAL (Seguridad).
    3. Lanza persistencia asíncrona (Eficiencia).
    """
    spend_key = f"spend:{tenant_id}:{cost_center}"
    
    try:
        # 1. ACTUALIZACIÓN INSTANTÁNEA (Redis - Hot Path)
        new_total = redis_client.incrbyfloat(spend_key, amount)
        
        # 2. WRITE-AHEAD LOG (WAL) - El seguro de vida
        # Creamos un paquete de datos inmutable
        charge_payload = {
            "id": str(uuid.uuid4()), # Idempotencia
            "tid": tenant_id,
            "cc": cost_center,
            "amt": amount,
            "ts": time.time()
        }
        raw_payload = json.dumps(charge_payload)
        
        # Guardamos en la cola ANTES de intentar procesar
        redis_client.rpush(WAL_QUEUE_KEY, raw_payload)
        
        # 3. PROCESAMIENTO ASÍNCRONO
        # Pasamos el raw_payload para poder borrarlo exactamente después
        asyncio.create_task(persist_spend_with_wal(charge_payload, raw_payload))
        
        return new_total

    except Exception as e:
        logger.error(f"❌ Redis Failure in increment_spend: {e}")
        # Fallback de emergencia: Intentar escribir directo a DB síncronamente
        # (Esto ralentiza la request pero salva el dinero si Redis falla)
        await _persist_to_db_core(tenant_id, cost_center, amount)
        return 0.0

async def persist_spend_with_wal(charge: dict, raw_payload: str):
    """
    Intenta guardar en DB y, si tiene éxito, borra del WAL.
    """
    try:
        # Intentamos guardar en Supabase
        success = await _persist_to_db_core(charge['tid'], charge['cc'], charge['amt'])
        
        if success:
            # ✅ ÉXITO: Borramos del WAL (ACK)
            # LREM borra 1 ocurrencia de ese string exacto
            redis_client.lrem(WAL_QUEUE_KEY, 1, raw_payload)
        else:
            # ⚠️ FALLO LÓGICO: Se queda en Redis para reintento futuro
            logger.warning(f"DB Write failed inside WAL logic for {charge['tid']}")
            
    except Exception as e:
        logger.error(f"CRITICAL: Async persistence crashed: {e}. Data remains in WAL for recovery.")

async def _persist_to_db_core(tenant_id: str, cost_center: str, amount: float) -> bool:
    """Núcleo de escritura en Supabase (RPC)"""
    try:
        loop = asyncio.get_running_loop()
        def _exec():
            return supabase.rpc("increment_spend", {
                "p_tenant_id": tenant_id,
                "p_cc_id": cost_center,
                "p_amount": amount
            }).execute()
        
        await loop.run_in_executor(None, _exec)
        return True
    except Exception as e:
        logger.error(f"Supabase RPC Error: {e}")
        return False

def recover_pending_charges():
    """
    🚑 RECOVERY WORKER (Se ejecuta al inicio)
    Revisa si quedaron cobros pendientes de un crash anterior y los procesa.
    """
    try:
        # Ver cuantos hay
        count = redis_client.llen(WAL_QUEUE_KEY)
        if count == 0:
            logger.info("✅ WAL Limpio. Sin cobros huérfanos.")
            return

        logger.warning(f"🚨 WAL DETECTADO: Recuperando {count} cobros huérfanos tras reinicio...")
        
        # Procesamos todo el backlog
        # Nota: En un sistema masivo, esto se haría por lotes.
        pending_items = redis_client.lrange(WAL_QUEUE_KEY, 0, -1)
        
        recovered = 0
        for raw in pending_items:
            try:
                data = json.loads(raw)
                # Ejecutamos síncronamente (bloqueante) para asegurar consistencia al arranque
                # Usamos la función rpc directamente
                supabase.rpc("increment_spend", {
                    "p_tenant_id": data['tid'],
                    "p_cc_id": data['cc'],
                    "p_amount": data['amt']
                }).execute()
                
                # Si funciona, borramos
                redis_client.lrem(WAL_QUEUE_KEY, 1, raw)
                recovered += 1
            except Exception as e:
                logger.error(f"Failed to recover item {raw}: {e}")
                
        logger.info(f"✅ Recuperación completada: {recovered}/{count} procesados.")
        
    except Exception as e:
        logger.critical(f"🔥 FATAL: Falló el worker de recuperación: {e}")