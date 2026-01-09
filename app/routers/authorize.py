# app/routers/authorize.py
import hashlib
import json
import os
from fastapi import APIRouter, Header, HTTPException, Depends, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.models import AuthorizeRequest, AuthorizeResponse
from app.db import supabase, redis_client
from app.logic import create_aut_token, get_active_policy
from app.webhooks import trigger_webhook
from datetime import datetime
from app.estimator import estimator

security = HTTPBearer()

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
    cached_tenant_id = await redis_client.get(cache_key)
    if cached_tenant_id:
        return cached_tenant_id

    # Check Database (Source of Truth)
    response = supabase.table("tenants").select("id, is_active").eq("api_key_hash", api_key_hash).execute()
    
    if not response.data:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    tenant = response.data[0]
    if not tenant['is_active']:
        raise HTTPException(status_code=403, detail="Tenant is inactive")

    # Guardar en Redis por 1 hora (TTL 3600)
    await redis_client.setex(cache_key, 3600, tenant['id'])
    
    return tenant['id']

# --- HELPER: Autenticación de Admin (JWT) ---
async def get_tenant_from_jwt(credentials: HTTPAuthorizationCredentials = Security(security)):
    """
    Valida el Token JWT de Supabase (Usuario Logueado) y devuelve su Tenant ID.
    Para Dashboard Web (Frontend).
    """
    token = credentials.credentials
    
    try:
        # 1. Validar Token contra Supabase Auth
        user_response = supabase.auth.get_user(token)
        user_id = user_response.user.id
        
        # 2. Buscar Tenant asociado al usuario (Owner)
        # Nota: Asumimos que existe un campo 'owner_id' en tenants o una tabla de mapeo.
        # Para MVP: Buscamos en 'tenants' donde 'owner_id' sea igual al user_id
        # Si no tienes owner_id, tendras que añadirlo: ALTER TABLE tenants ADD COLUMN owner_id UUID;
        
        # Cache Strategy
        cache_key = f"tenant:owner:{user_id}"
        cached_tenant = await redis_client.get(cache_key)
        if cached_tenant: return cached_tenant
        
        # DB Lookup
        res = supabase.table("tenants").select("id").eq("owner_id", user_id).execute()
        
        if not res.data:
            # Fallback: Si no tiene tenant propio, error.
            raise HTTPException(status_code=403, detail="User has no associated tenant")
            
        tenant_id = res.data[0]['id']
        await redis_client.setex(cache_key, 300, tenant_id) # Cache 5 min
        
        return tenant_id
        
    except Exception as e:
        # Si Supabase falla validando el token
        raise HTTPException(status_code=401, detail="Invalid Session Token")



# --- HELPER: Obtener Gasto Actual ---
async def get_current_spend(tenant_id: str, cost_center_id: str):
    """
    Lee de Redis (tiempo real). Si no existe, hidrata desde DB.
    """
    key = f"spend:{tenant_id}:{cost_center_id}"
    spend = await redis_client.get(key)
    
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
        await redis_client.set(key, val)
        return val
    
    return 0.0

from app.limiter import limiter

# --- ENDPOINT PRINCIPAL ---
@router.post("/v1/authorize", response_model=AuthorizeResponse)
@limiter.limit("50/second")
async def authorize_transaction(
    request: Request, # SlowAPI necesita el objeto Request
    req: AuthorizeRequest, 
    tenant_id: str = Depends(get_tenant_from_header)
):
    # 0. Contexto
    policy = await get_active_policy(tenant_id)
    current_spend = await get_current_spend(tenant_id, req.cost_center_id)
    
    # Check Panic Mode
    if policy.get("panic_mode", False):
         return AuthorizeResponse(
            decision="DENIED", 
            authorization_id="panic", 
            reason_code="EMERGENCY STOP ACTIVE"
        )
    
    # 1. PREDICT: Estimación Multimodal (Zero-History)
    # Obtenemos el tipo de tarea de la política (configuración) o metadatos
    # Prioridad: Metadata > Policy > Default
    task_type = req.metadata.get("task_type") or policy.get("task_type", "DEFAULT")
    
    # Determinar cantidad de entrada (Tokens, Minutos, Imagenes)
    # Usamos input_unit_count si viene, sino est_input_tokens (backward compatibility)
    input_qty = req.input_unit_count if req.input_unit_count > 0 else req.est_input_tokens
    if input_qty <= 0: input_qty = 100 # Fallback minimo
    
    # Caso especial: Si es IMG_GENERATION y no viene count, buscamos en metadata 'num_images'
    if "IMG_GENERATION" in task_type and input_qty <= 1:
        input_qty = float(req.metadata.get("num_images", 1))
        
    # Caso especial: Si es AUDIO y no viene count, buscamos 'duration_seconds'
    if "AUDIO" in task_type and input_qty <= 1:
        secs = float(req.metadata.get("duration_seconds", 60))
        input_qty = secs / 60.0 # Minutos

    # Calcular Coste Estimado
    cost_estimated = await estimator.estimate_cost(
        model=req.model,
        task_type=task_type,
        input_unit_count=input_qty,
        metadata=req.metadata
    )
    
    # --- 0. EU AI ACT COMPLIANCE CHECK (2026) ---
    risk_config = policy.get("risk_management", {})
    risk_rules = risk_config.get("rules", {})
    
    # Determinamos la acción legal basada en el caso de uso
    # Default a ALLOW si no está definido (o si es policy vieja 1.0)
    action = risk_rules.get(req.use_case.value, "ALLOW")
    
    # LÓGICA DE RIESGOS
    if action == "PROHIBITED":
        # Caso: Biometría o Social Scoring -> Bloqueo Inmediato
        return AuthorizeResponse(
            decision="DENIED",
            authorization_id="risk-block", # No generamos ID formal si es prohibido
            reason_code=f"EU AI Act Violation: Usage '{req.use_case.value}' is PROHIBITED.",
            execution_mode="BLOCKED"
        )

    elif action == "HUMAN_CHECK":
        # Caso: RRHH o Medicina -> Forzamos "Pending Approval"
        decision = "PENDING_APPROVAL"
        reason = f"High Risk Use Case ({req.use_case.value}). Human verification required by law."
        
    elif action == "LOG_AUDIT":
        # Caso: Finanzas -> Marcamos para auditoría extendida
        req.metadata["compliance_level"] = "high_risk_audit"
    
    # 2. CHECK: Reglas de Presupuesto GLOBAL
    monthly_limit = policy.get("limits", {}).get("monthly", 0)
    
    # Initialize decision for non-blocking risk actions
    if action == "ALLOW" or action == "LOG_AUDIT":
         decision = "APPROVED"
         reason = "Policy check passed"

    # No indentation needed for subsequent checks as they guard with 'if decision == "APPROVED"'
    
    # --- GOVERNANCE: Human-in-the-Loop (APPROVALS) ---
    governance = policy.get("governance", {})
    approval_threshold = governance.get("require_approval_above_cost", 0)
    
    if approval_threshold > 0 and cost_estimated >= approval_threshold:
        decision = "PENDING_APPROVAL"
        reason = f"High cost action ({cost_estimated:.4f} > {approval_threshold}). Manager approval required."
    
    # Check Budget (Solo si no está pendiente de aprobación)
    if decision == "APPROVED" and monthly_limit > 0 and (current_spend + cost_estimated) > monthly_limit:
        decision = "DENIED"
        reason = f"Monthly budget exceeded. Used: {current_spend:.4f}, Est Cost: {cost_estimated:.4f}, Limit: {monthly_limit}"

    # Reglas Per Request y Actor (Granular)
    limits_config = policy.get("limits", {})
    actor_limit = limits_config.get("actors", {}).get(req.actor_id)
    global_per_req = limits_config.get("per_request", 0)
    effective_limit = actor_limit if actor_limit is not None else global_per_req

    if decision == "APPROVED" and effective_limit > 0 and cost_estimated > effective_limit:
        decision = "DENIED"
        reason = f"Request limit exceeded. Est Cost: {cost_estimated:.4f} > Limit: {effective_limit}"

    # Regla Allowlist
    allowed_models = policy.get("allowlist", {}).get("models", [])
    if decision == "APPROVED" and allowed_models and req.model not in allowed_models:
        decision = "DENIED"
        reason = f"Model '{req.model}' not in allowlist"

    # --- 3. SMART ROUTING (THE BROKER) ---
    routing_config = policy.get("smart_routing", {})
    suggested_model = None
    
    # Si tenemos una decisión DENIED por presupuesto, intentamos salvarla
    if decision == "DENIED" and "budget exceeded" in reason.lower() and routing_config.get("enabled", False):
        
        # Buscar fallbacks
        fallbacks = routing_config.get("fallbacks", {}).get(req.model, [])
        
        for fallback_model in fallbacks:
            # 1. Ver si fallback está permitido
            if allowed_models and fallback_model not in allowed_models:
                continue 
                
            # 2. Predecir coste fallback (Estimador Multimodal)
            f_cost_est = await estimator.estimate_cost(
                model=fallback_model,
                task_type=task_type,
                input_unit_count=input_qty,
                metadata=req.metadata
            )
            
            # 3. Check presupuesto con nuevo coste
            budget_fits = True
            if monthly_limit > 0 and (current_spend + f_cost_est) > monthly_limit:
                budget_fits = False
            
            # 4. Check límite request con nuevo coste
            if budget_fits and effective_limit > 0 and f_cost_est > effective_limit:
                budget_fits = False
                
            if budget_fits:
                # ¡ENCONTRADO UN SALVAVIDAS!
                decision = "APPROVED"
                reason = f"Switched to {fallback_model} to fit budget."
                suggested_model = fallback_model
                break

    # 4. Persistencia (Audit)
    auth_log = supabase.table("authorizations").insert({
        "tenant_id": tenant_id,
        "cost_center_id": req.cost_center_id,
        "actor_id": req.actor_id,
        "decision": decision,
        "max_amount": req.max_amount, # guardamos el original del cliente
        "provider": req.provider,
        "model": req.model,
        "estimated_cost": cost_estimated,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    auth_id = auth_log.data[0]['id']

    # --- SHADOW MODE & ALERTS (TRANSPARENCY 2026) ---
    policy_mode = policy.get("mode", "active")
    execution_mode = "ACTIVE"
    
    if decision == "DENIED":
        # Disparamos alerta SIEMPRE (para que el admin sepa que algo falló o se bloqueó)
        await trigger_webhook(tenant_id, "authorization.denied", {
            "actor_id": req.actor_id,
            "reason": reason,
            "decision": decision,
            "cost_estimated": cost_estimated,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        if policy_mode == "shadow":
            decision = "APPROVED"
            reason = f"[SHADOW MODE] Originally DENIED: {reason}"
            execution_mode = "SHADOW_SIMULATION"
        else:
             return AuthorizeResponse(
                decision="DENIED",
                authorization_id=auth_id,
                reason_code=reason,
                estimated_cost=cost_estimated,
                execution_mode="ACTIVE"
            )
    else:
        execution_mode = "ACTIVE"

    # 5. Generar Token (Aprobado)
    token_payload = {
        "sub": req.actor_id,
        "tid": tenant_id,
        "cc": req.cost_center_id,
        "pol": auth_id,
        # Si cambiamos modelo, el recibo deberia reflejarlo? 
        # El token es agnóstico del modelo, pero autoriza el gasto.
        "est": cost_estimated,
        "prov": req.provider
    }
    
    signed_token = create_aut_token(token_payload)

    return AuthorizeResponse(
        decision="APPROVED",
        aut_token=signed_token,
        authorization_id=auth_id,
        suggested_model=suggested_model,
        reason_code=reason,
        estimated_cost=cost_estimated,
        execution_mode=execution_mode # Transparencia Total
    )