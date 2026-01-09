# app/logic.py
import os
import time
from jose import jwt
from app.db import supabase, redis_client
from fastapi import HTTPException
import json

# Estas variables DEBEN estar en tu entorno de Render (.env)
SECRET_KEY = os.getenv("ASARL_SECRET_KEY") 
if not SECRET_KEY:
    raise ValueError("FATAL: ASARL_SECRET_KEY not set in environment")

ALGORITHM = "HS256"

def create_aut_token(data: dict):
    to_encode = data.copy()
    # Expire en 10 minutos (tiempo suficiente para ejecutar el prompt y volver)
    expire = time.time() + 600 
    to_encode.update({"exp": expire, "iss": "agentshield-core"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def sign_receipt(receipt_data: dict):
    # Firma inmutable del recibo
    return jwt.encode(receipt_data, SECRET_KEY, algorithm=ALGORITHM)

def check_policy(policy_rules, request_data, current_spend, monthly_limit):
    # 1. Check presupuesto
    if (current_spend + request_data.max_amount) > monthly_limit:
        return False, "Budget Exceeded"
    
    # 2. Check Max Request (ejemplo simple)
    if request_data.max_amount > policy_rules.get("max_per_request", 100):
        return False, "Request limit exceeded"
        
    return True, "Approved"

# --- DATA RESIDENCY ---
CURRENT_SERVER_REGION = os.getenv("SERVER_REGION", "eu") 

async def verify_residency(tenant_id: str):
    # Buscamos la región del tenant (idealmente en caché de Redis)
    tenant_region = await redis_client.get(f"region:{tenant_id}")
    
    if not tenant_region:
        res = supabase.table("tenants").select("region").eq("id", tenant_id).single().execute()
        tenant_region = res.data.get("region", "eu") # Default fallback
        await redis_client.set(f"region:{tenant_id}", tenant_region, ex=3600)
    else:
        tenant_region = tenant_region.decode('utf-8')

    # Si la región del cliente no coincide con la del servidor actual, BLOQUEAMOS
    if tenant_region != CURRENT_SERVER_REGION:
        raise HTTPException(
            status_code=451, # Unavailable For Legal Reasons
            detail=f"Data Residency: Your data is hosted in {tenant_region}. Please use the correct regional endpoint."
        )

# --- HELPER: Obtener Política Activa (Shared Logic) ---
async def get_active_policy(tenant_id: str):
    """
    Recupera la política activa. Cachea en Redis por 5 minutos.
    """
    cache_key = f"policy:active:{tenant_id}"
    cached_policy = await redis_client.get(cache_key)
    
    if cached_policy:
        return json.loads(cached_policy)

    # Fallback a DB
    response = supabase.table("policies")\
        .select("rules")\
        .eq("tenant_id", tenant_id)\
        .eq("is_active", True)\
        .order("version", desc=True)\
        .limit(1)\
        .execute()

    if not response.data:
        return {"limits": {"monthly": 0, "per_request": 0}}

    policy_rules = response.data[0]['rules']
    await redis_client.setex(cache_key, 300, json.dumps(policy_rules))
    
    return policy_rules