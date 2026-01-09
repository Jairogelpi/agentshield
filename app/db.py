# agentshield_core/app/db.py
import os
from app.utils import fast_json as json
import uuid
from supabase import create_client, Client
import redis.asyncio as redis
import asyncio
import logging
import time

from decimal import Decimal
import logging

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
    spend = await redis_client.get(key)
    if spend: return float(spend)
    
    loop = asyncio.get_running_loop()
    def _fetch():
        return supabase.table("cost_centers").select("current_spend").eq("tenant_id", tenant_id).eq("id", cost_center).execute()
    
    res = await loop.run_in_executor(None, _fetch)
    if res.data:
        val = res.data[0]['current_spend']
        await redis_client.set(key, val)
        return float(val)
    return 0.0

async def increment_spend(tenant_id: str, cost_center: str, amount: Decimal, metadata: dict = None):
    """
    1. Actualiza Redis (Velocidad).
    2. Escribe en WAL (Seguridad).
    3. Lanza persistencia asíncrona (Eficiencia).
    """
    spend_key = f"spend:{tenant_id}:{cost_center}"
    
    try:
        # Convert Decimal to float just for Redis (Redis requires float/string)
        # But we keep precision in the WAL payload
        amount_float = float(amount)
        
        # 1. ACTUALIZACIÓN INSTANTÁNEA (Redis - Hot Path)
        new_total = await redis_client.incrbyfloat(spend_key, amount_float)
        
        # 2. WRITE-AHEAD LOG (WAL) - El seguro de vida
        # Creamos un paquete de datos inmutable
        charge_payload = {
            "id": str(uuid.uuid4()), # Idempotencia
            "tid": tenant_id,
            "cc": cost_center,
            "amt": str(amount), # Serialize as String to preserve precision in JSON
            "ts": time.time(),
            "meta": metadata or {}
        }
        
        # 3. DOUBLE WRITE STRATEGY (Redis WAL + Supabase Log)
        # Lanzamos ambas escrituras de seguridad.
        # Si Redis muere, queda el Log en PG. Si PG está lento, Redis responde rápido.
        loop = asyncio.get_running_loop()
        
        # A. Escribir en Tabla de Logs (Caja Negra) - Fire & Forget optimizado
        # No esperamos a que termine para no penalizar latencia, pero se lanza.
        log_task = loop.run_in_executor(None, lambda: supabase.table("pending_transactions_log").insert({
            "trace_id": (metadata or {}).get("trace_id", str(uuid.uuid4())),
            "tenant_id": tenant_id,
            "cost_center_id": cost_center,
            "amount": float(amount), # Postgres numeric accepts float, but string is safer if supported
            "metadata": metadata or {},
            "status": "PENDING"
        }).execute())
        
        # B. Escribir en Redis WAL (Cola de Procesamiento Real)
        wal_task = redis_client.rpush(WAL_QUEUE_KEY, json.dumps(charge_payload))
        
        # Esperamos solo al WAL de Redis (es ultra rápido y es nuestro source of truth primario)
        await wal_task
        
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
            await redis_client.lrem(WAL_QUEUE_KEY, 1, raw_payload)
        else:
            # ⚠️ FALLO LÓGICO: Se queda en Redis para reintento futuro
            logger.warning(f"DB Write failed inside WAL logic for {charge['tid']}")
            
    except Exception as e:
        logger.error(f"CRITICAL: Async persistence crashed: {e}. Data remains in WAL for recovery.")

async def _persist_to_db_core(tenant_id: str, cost_center: str, amount: Decimal) -> bool:
    """Núcleo de escritura en Supabase (RPC)"""
    try:
        loop = asyncio.get_running_loop()
        def _exec():
            return supabase.rpc("increment_spend", {
                "p_tenant_id": tenant_id,
                "p_cc_id": cost_center,
                "p_amount": float(amount) # RPC parameter
            }).execute()
        
        await loop.run_in_executor(None, _exec)
        return True
    except Exception as e:
        logger.error(f"Supabase RPC Error: {e}")
        return False

async def recover_pending_charges():
    """
    🚑 RECOVERY WORKER (Se ejecuta al inicio)
    Revisa si quedaron cobros pendientes de un crash anterior y los procesa.
    """
    try:
        # Ver cuantos hay
        count = await redis_client.llen(WAL_QUEUE_KEY)
        if count == 0:
            logger.info("✅ WAL Limpio. Sin cobros huérfanos.")
            return

        logger.warning(f"🚨 WAL DETECTADO: Recuperando {count} cobros huérfanos tras reinicio...")
        
        # Procesamos todo el backlog
        # Nota: En un sistema masivo, esto se haría por lotes.
        pending_items = await redis_client.lrange(WAL_QUEUE_KEY, 0, -1)
        
        recovered = 0
        loop = asyncio.get_running_loop()
        
        for raw in pending_items:
            try:
                data = json.loads(raw)
                # Ejecutamos en executor para no bloquear el loop principal si tarda
                # Usamos la función rpc directamente
                def _exec_recovery():
                    return supabase.rpc("increment_spend", {
                        "p_tenant_id": data['tid'],
                        "p_cc_id": data['cc'],
                        "p_amount": data['amt']
                    }).execute()
                
                await loop.run_in_executor(None, _exec_recovery)
                
                # Si funciona, borramos
                await redis_client.lrem(WAL_QUEUE_KEY, 1, raw)
                recovered += 1
            except Exception as e:
                logger.error(f"Failed to recover item {raw}: {e}")
                
        logger.info(f"✅ Recuperación completada: {recovered}/{count} procesados.")
        
    except Exception as e:
        logger.critical(f"🔥 FATAL: Falló el worker de recuperación: {e}")