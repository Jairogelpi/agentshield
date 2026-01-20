# agentshield_core/app/db.py
import asyncio
import logging
import os
import time
import uuid
from datetime import datetime
from decimal import Decimal

import redis.asyncio as redis
from supabase import Client, create_client

from app.utils import fast_json as json

logger = logging.getLogger("agentshield.db")

# Configuración
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
REDIS_URL = os.getenv("REDIS_URL")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
redis_client = redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_timeout=5.0,
    socket_connect_timeout=5.0,
    retry_on_timeout=True
)

# Nombre de la cola de seguridad (WAL)
WAL_QUEUE_KEY = "wal:pending_charges"


async def get_current_spend(tenant_id: str, cost_center: str):
    """Lectura optimista desde Redis con Fallback a DB"""
    key = f"spend:{tenant_id}:{cost_center}"
    spend = await redis_client.get(key)
    if spend:
        return float(spend)

    loop = asyncio.get_running_loop()

    def _fetch():
        return supabase.table("cost_centers").select("current_spend").eq("tenant_id", tenant_id).eq("id", cost_center).execute()

    res = await loop.run_in_executor(None, _fetch)
    if res.data:
        val = res.data[0]['current_spend']
        # FIX: Evitar Race Condition "Check-Then-Set"
        # Usamos setnx (Set if Not Exists) para no sobrescribir incrementos concurrentes
        # que hayan ocurrido mientras consultábamos la DB.
        # Si ya existe, NO lo tocamos (respetamos la verdad parcial de Redis que es más reciente).
        await redis_client.setnx(key, val)
        return float(val)
    return 0.0


async def increment_spend(tenant_id: str, cost_center: str, amount: Decimal, metadata: dict = None):
    """
    1. Actualiza Redis (Velocidad). Soporta importes negativos (Earnings).
    2. Escribe en WAL (Seguridad).
    3. Lanza persistencia asíncrona (Eficiencia).
    """
    spend_key = f"spend:{tenant_id}:{cost_center}"
    spend_key_total = f"spend:{tenant_id}:total"  # <--- CLAVE FALTANTE (Fix Financiero)

    try:
        # Convert Decimal to float just for Redis (Redis requires float/string)
        # But we keep precision in the WAL payload
        amount_float = float(amount)

        # 1. ACTUALIZACIÓN ATÓMICA (Redis - Hot Path)
        # Sigue siendo la fuente de verdad para la limitación de tasa (Rate Limiting)
        # Pipeline para atomicidad entre CC y TOTAL
        pipe = redis_client.pipeline()
        pipe.incrbyfloat(spend_key, amount_float)
        pipe.incrbyfloat(spend_key_total, amount_float)  # <--- FIX: Actualizamos TOTAL
        results = await pipe.execute()

        new_total_cc = results[0]

        # 2. STREAM BUFFER (Alta Velocidad)
        event_payload = {
            "tid": tenant_id,
            "cc": cost_center,
            "amt": str(amount),
            "ts": str(time.time()),
            "meta": json.dumps(metadata or {})
        }

        # Añadimos al stream 'billing:stream'
        await redis_client.xadd("billing:stream", event_payload, maxlen=100000, approximate=True)

        # 3. WAL DE SEGURIDAD (Backup para Crash Recovery)
        # Guardamos TAMBIÉN en la lista. El worker, cuando procese el stream con éxito,
        # deberá borrar este item de la lista (LREM) usando persist_spend_with_wal.
        # Esto garantiza que si el worker muere, recover_pending_charges encontrará los datos.
        wal_payload = json.dumps({
            "tid": tenant_id,
            "cc": cost_center,
            "amt": float(amount)
        })
        await redis_client.rpush(WAL_QUEUE_KEY, wal_payload)  # <--- FIX: Double Write

        return new_total_cc

    except Exception as e:
        logger.error(f"❌ Redis Failure in increment_spend: {e}")
        # Fallback de emergencia: Intentar escribir directo a DB síncronamente
        # (Esto ralentiza la request pero salva el dinero si Redis falla totalmente)
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
                "p_amount": float(amount)  # RPC parameter
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


async def get_function_config(tenant_id: str, func_id: str) -> dict:
    if not func_id:
        return None

    # 1. Cache Key
    key = f"func_conf:{tenant_id}:{func_id}"

    # 2. Redis
    cached = await redis_client.get(key)
    if cached:
        return json.loads(cached)

    # 3. Supabase
    loop = asyncio.get_running_loop()

    def _fetch():
        return supabase.table("function_configs")\
            .select("*")\
            .eq("tenant_id", tenant_id)\
            .eq("function_id", func_id)\
            .maybe_single()\
            .execute()

    res = await loop.run_in_executor(None, _fetch)

    if res.data:
        config = res.data

        # --- LÓGICA DE CENICIENTA (Lazy Reset) ---
        # Si last_used es de ayer y hay gasto acumulado, reiniciamos a 0.
        try:
            last_used_str = config.get('last_used')
            if last_used_str:
                # Ajuste de zona horaria simple (Z -> +00:00 para Python isoformat)
                last_used_dt = datetime.fromisoformat(last_used_str.replace('Z', '+00:00'))
                today = datetime.utcnow().date()

                if last_used_dt.date() < today and config.get('current_spend_daily', 0) > 0:
                    # 1. Reiniciamos en background (Fire & Forget)
                    asyncio.create_task(_reset_daily_spend(tenant_id, func_id))
                    # 2. Falseamos el dato localmente para permitir esta request
                    config['current_spend_daily'] = 0.0
        except Exception as e:
            logger.warning(f"Lazy Reset logic check failed: {e}")

        # Guardar en Redis y Actualizar heartbet
        await redis_client.setex(key, 60, json.dumps(config))
        asyncio.create_task(_touch_function_last_used(tenant_id, func_id))
        return config

    return None


# Función auxiliar necesaria para el reinicio
async def _reset_daily_spend(tid, fid):
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: supabase.table("function_configs").update({"current_spend_daily": 0}).eq("tenant_id", tid).eq("function_id", fid).execute()
        )
    except Exception as e:
        logger.warning(f"Failed to reset daily spend for {fid}: {e}")


async def _touch_function_last_used(tid, fid):
    """Actualiza la fecha de uso para saber qué funciones están vivas"""
    try:
        loop = asyncio.get_running_loop()

        def _update():
            return supabase.table("function_configs").update({"last_used": "now()"}).eq("tenant_id", tid).eq("function_id", fid).execute()

        await loop.run_in_executor(None, _update)
    except Exception as e:
        logger.warning(f"Failed to touch last_used for {fid}: {e}")