# app/logic.py
import os
import time
import hashlib
import asyncio
from jose import jwt, JWTError
from app.db import supabase, redis_client
from fastapi import HTTPException
import json
import logging

logger = logging.getLogger("agentshield.auth")

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

# --- NUEVA FUNCIÓN: VALIDACIÓN HÍBRIDA (API KEY + JWT) ---
async def verify_api_key(auth_header: str) -> str:
    """
    Verifica la identidad del cliente de forma segura.
    Soporta:
    1. Bearer JWT (Firmado por nosotros) -> Para Frontend/Dashboard
    2. Bearer sk_live_... (API Key Opaca) -> Para Scripts/Backend (Hash Lookup)
    
    Retorna: tenant_id (str) o lanza 401.
    """
    if not auth_header:
        raise HTTPException(401, "Missing Authorization Header")

    token = auth_header.replace("Bearer ", "").strip()
    
    # ESTRATEGIA A: JWT (Token largo con puntos)
    if len(token) > 50 and token.count(".") == 2:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            # Validar expiración y emisor es automático por jose si se configura, 
            # pero aquí confiamos en la firma.
            return payload.get("tenant_id")
        except JWTError:
            raise HTTPException(401, "Invalid or Expired JWT")

    # ESTRATEGIA B: API KEY (Opaque Token -> Hash Lookup)
    # 1. Hashing SHA256 (Nunca enviamos la key cruda a la DB/Logs)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # 2. Check Caché Redis (Velocidad Luz: 2ms)
    cache_key = f"auth:apikey:{token_hash}"
    cached_tenant = await redis_client.get(cache_key)
    
    if cached_tenant:
        return cached_tenant.decode() # Redis devuelve bytes
        
    # 3. Check Base de Datos (Supabase)
    # Usamos run_in_executor para no bloquear el Event Loop con la llamada HTTP sincrona de Supabase
    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(
            None, 
            lambda: supabase.table("tenants").select("id").eq("api_key_hash", token_hash).execute()
        )
        
        if res.data and len(res.data) > 0:
            tenant_id = res.data[0]['id']
            # Guardamos en caché por 15 minutos (LRU implícito por TTL)
            await redis_client.setex(cache_key, 900, tenant_id)
            return tenant_id
            
        # 3.1. FALLBACK: Check Llave Secundaria (Zero-Downtime Rotation)
        # Si la llave primaria falló, buscamos si es una secundaria válida (expira en 24h)
        res_sec = await loop.run_in_executor(
            None, 
            lambda: supabase.table("tenants")
                .select("id")
                .eq("api_key_hash_secondary", token_hash)
                .gt("api_key_secondary_expires_at", "now()") # Solo si no ha expirado
                .execute()
        )
        if res_sec.data and len(res_sec.data) > 0:
            tenant_id = res_sec.data[0]['id']
            # Cacheamos (quizás con TTL menor, ya que está muriendo)
            await redis_client.setex(cache_key, 300, tenant_id)
            return tenant_id
            
    except Exception as e:
        logger.error(f"Auth DB Error: {e}", exc_info=True)
        
    # Si llegamos aquí, nadie reconoció la llave
    logger.warning(f"Authentication failed for hash: {token_hash[:8]}...")
    raise HTTPException(401, "Invalid API Key")

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
        if tenant_region == "eu":
             logger.warning(f"Tenant {tenant_id} region not found, defaulting to 'eu'. Check DB integrity.")
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