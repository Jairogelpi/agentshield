import os
from supabase import create_client, Client
import redis

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
    try:
        # 1. Llamada RPC a Supabase (Source of Truth)
        # Esto garantiza atomicidad en la base de datos.
        response = supabase.rpc("increment_spend", {
            "p_tenant_id": tenant_id,
            "p_cc_id": cost_center,
            "p_amount": amount
        }).execute()
        
        # Obtenemos el nuevo total confirmado por la DB
        new_total_spend = response.data 

        # 2. Actualizamos Redis con el valor REAL de la DB
        # No hacemos "incrby" aquí para evitar desvío (drift) entre DB y Cache.
        # Simplemente imponemos la verdad de la DB en el caché.
        key = f"spend:{tenant_id}:{cost_center}"
        redis_client.set(key, new_total_spend)
        
        return new_total_spend

    except Exception as e:
        # En producción, aquí va un log crítico a Sentry/Datadog
        print(f"CRITICAL ERROR updating spend: {e}")
        raise e