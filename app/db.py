import os
from supabase import create_client, Client
import redis
import asyncio

# Configuración
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY") # Service role key!
REDIS_URL = os.getenv("REDIS_URL")

# Clientes
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

async def get_current_spend(tenant_id: str, cost_center: str):
    # Intentar leer de Redis primero (caché caliente)
    key = f"spend:{tenant_id}:{cost_center}"
    spend = redis_client.get(key)
    if spend:
        return float(spend)
    
    # Fallback a DB si Redis está vacío (cold start)
    res = supabase.table("cost_centers").select("current_spend").eq("tenant_id", tenant_id).eq("id", cost_center).execute()
    if res.data:
        val = res.data[0]['current_spend']
        redis_client.set(key, val)
        return float(val)
    return 0.0

# app/db.py

async def increment_spend(tenant_id: str, cost_center: str, amount: float):
    """
    Actualiza el gasto usando Write-Behind Caching.
    Prioriza la velocidad en Redis y delega la DB a un proceso asíncrono.
    """
    key = f"spend:{tenant_id}:{cost_center}"
    
    try:
        # 1. ACTUALIZACIÓN INSTANTÁNEA (Redis)
        # Usamos incrbyfloat para que el límite de presupuesto se aplique al milisegundo
        new_redis_total = redis_client.incrbyfloat(key, amount)
        
        # 2. PERSISTENCIA ASÍNCRONA (Fire and Forget)
        # No usamos 'await' aquí para la DB, lo lanzamos como una tarea de fondo
        asyncio.create_task(persist_spend_to_db(tenant_id, cost_center, amount))
        
        return new_redis_total

    except Exception as e:
        print(f"❌ Error updating Redis spend: {e}")
        # Si falla Redis, intentamos al menos registrar en DB de forma síncrona como fallback
        return await persist_spend_to_db(tenant_id, cost_center, amount)

async def persist_spend_to_db(tenant_id: str, cost_center: str, amount: float):
    """
    Tarea de fondo para persistir el gasto en Supabase.
    """
    try:
        response = supabase.rpc("increment_spend", {
            "p_tenant_id": tenant_id,
            "p_cc_id": cost_center,
            "p_amount": amount
        }).execute()
        return response.data
    except Exception as e:
        # Log crítico si la DB falla, para reintentar o auditar después
        print(f"CRITICAL: DB Persistence failed for {tenant_id}: {e}")
        return None