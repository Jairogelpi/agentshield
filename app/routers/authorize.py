# app/routers/authorize.py
import hashlib
import json
import os
from fastapi import APIRouter, Header, HTTPException, Depends
from app.models import AuthorizeRequest, AuthorizeResponse
from app.db import supabase, redis_client
from app.logic import create_aut_token
from datetime import datetime

router = APIRouter()

# --- HELPER: Autenticación de Tenant (Production Grade) ---
async def get_tenant_from_header(x_api_key: str = Header(...)):
    """
    1. Hashea la API Key entrante.
    2. Busca en Redis (Cache Hit).
    3. Si falla, busca en Supabase (Cache Miss) y guarda en Redis.
    """
    # Hash SHA256 para no mover keys en plano
    api_key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    
    # Check Redis Cache
    cache_key = f"tenant:apikey:{api_key_hash}"
    cached_tenant_id = redis_client.get(cache_key)
    if cached_tenant_id:
        return cached_tenant_id

    # Check Database (Source of Truth)
    # Asumimos que en la tabla tenants tienes columna 'api_key_hash'
    response = supabase.table("tenants").select("id, is_active").eq("api_key_hash", api_key_hash).execute()
    
    if not response.data:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    tenant = response.data[0]
    if not tenant['is_active']:
        raise HTTPException(status_code=403, detail="Tenant is inactive")

    # Guardar en Redis por 1 hora (TTL 3600) para velocidad extrema
    redis_client.setex(cache_key, 3600, tenant['id'])
    
    return tenant['id']

# --- HELPER: Obtener Política Activa ---
def get_active_policy(tenant_id: str):
    """
    Recupera la política activa. Cachea en Redis por 5 minutos.
    """
    cache_key = f"policy:active:{tenant_id}"
    cached_policy = redis_client.get(cache_key)
    
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
        # Default policy restrictiva si no hay configuración
        return {"limits": {"monthly": 0, "per_request": 0}}

    policy_rules = response.data[0]['rules']
    # Cachear 5 min (300s) para permitir cambios rápidos pero no saturar DB
    redis_client.setex(cache_key, 300, json.dumps(policy_rules))
    
    return policy_rules

# --- HELPER: Obtener Gasto Actual ---
def get_current_spend(tenant_id: str, cost_center_id: str):
    """
    Lee de Redis (tiempo real). Si no existe, hidrata desde DB.
    """
    key = f"spend:{tenant_id}:{cost_center_id}"
    spend = redis_client.get(key)
    
    if spend is not None:
        return float(spend)
    
    # Hidratar desde DB
    response = supabase.table("cost_centers")\
        .select("current_spend")\
        .eq("tenant_id", tenant_id)\
        .eq("id", cost_center_id)\
        .execute()
        
    if response.data:
        val = float(response.data[0]['current_spend'])
        redis_client.set(key, val)
        return val
    
    # Si el cost center no existe, asumimos 0 (o podrías lanzar error 404 estricto)
    return 0.0

# --- ENDPOINT PRINCIPAL ---
@router.post("/v1/authorize", response_model=AuthorizeResponse)
async def authorize_transaction(
    req: AuthorizeRequest, 
    tenant_id: str = Depends(get_tenant_from_header)
):
    # 1. Obtener Datos de Contexto
    policy = get_active_policy(tenant_id)
    current_spend = get_current_spend(tenant_id, req.cost_center_id)
    
    # Variables de decisión
    decision = "APPROVED"
    reason = "Policy check passed"
    
    # 2. Motor de Reglas (Logic Core)
    # A) Check Monthly Budget
    # Asumimos estructura del JSON de policy: {"limits": {"monthly": 1000, "per_request": 5}}
    monthly_limit = policy.get("limits", {}).get("monthly", 0)
    
    if monthly_limit > 0 and (current_spend + req.max_amount) > monthly_limit:
        decision = "DENIED"
        reason = f"Monthly budget exceeded. Used: {current_spend}, Requested: {req.max_amount}, Limit: {monthly_limit}"

    # B) Check Per-Request Limit
    per_req_limit = policy.get("limits", {}).get("per_request", 0)
    if decision == "APPROVED" and per_req_limit > 0 and req.max_amount > per_req_limit:
        decision = "DENIED"
        reason = f"Request limit exceeded. Max allowed: {per_req_limit}"

    # C) Check Provider/Model Allowlist
    allowed_models = policy.get("allowlist", {}).get("models", [])
    if decision == "APPROVED" and allowed_models and req.model not in allowed_models:
        decision = "DENIED"
        reason = f"Model '{req.model}' not in allowlist"

    # 3. Persistencia de la Decisión (Auditoría)
    # Insertamos en DB sin esperar (bloqueante mínimo) o background task
    auth_log = supabase.table("authorizations").insert({
        "tenant_id": tenant_id,
        "cost_center_id": req.cost_center_id,
        "actor_id": req.actor_id,
        "decision": decision,
        "max_amount": req.max_amount,
        "provider": req.provider,
        "model": req.model,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    auth_id = auth_log.data[0]['id']

    # 4. Generar Respuesta
    if decision == "DENIED":
        # Retornamos 200 OK con decisión DENIED (el cliente debe manejarlo) 
        # o 403. Para APIs de este tipo, 403 suele ser más semántico para "Forbidden".
        # Aquí seguimos el schema de respuesta:
        return AuthorizeResponse(
            decision="DENIED",
            authorization_id=auth_id,
            reason_code=reason
        )

    # 5. Si es APROBADO -> Firmar Token
    # El payload del token lleva los datos necesarios para el receipt posterior
    token_payload = {
        "sub": req.actor_id,
        "tid": tenant_id,
        "cc": req.cost_center_id,
        "pol": auth_id, # Vinculamos al log de autorización
        "max": req.max_amount,
        "prov": req.provider
    }
    
    signed_token = create_aut_token(token_payload)

    return AuthorizeResponse(
        decision="APPROVED",
        aut_token=signed_token,
        authorization_id=auth_id
    )