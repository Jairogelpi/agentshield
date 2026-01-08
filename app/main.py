from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
from .db import supabase, get_current_spend, increment_spend
from .logic import create_aut_token, check_policy, sign_receipt

app = FastAPI(title="ASARL Engine")

class AuthorizeRequest(BaseModel):
    actor_id: str
    cost_center: str
    max_amount: float
    provider: str

@app.post("/v1/authorize")
async def authorize(req: AuthorizeRequest, x_tenant_key: str = Header(...)):
    # 1. Validar Tenant (Simulado, deberías hashear y buscar en DB)
    # tenant = get_tenant_by_key(x_tenant_key)
    tenant_id = "uuid-del-tenant" # Hardcodeado para ejemplo
    
    # 2. Obtener estado financiero (Redis/DB)
    current_spend = await get_current_spend(tenant_id, req.cost_center)
    
    # 3. Obtener Policy (Podrías cachear esto en Redis también)
    # policy = ...
    policy_rules = {"max_per_request": 5.0} # Dummy
    monthly_limit = 1000.0 # Dummy
    
    # 4. Motor de decisión
    approved, reason = check_policy(policy_rules, req, current_spend, monthly_limit)
    
    if not approved:
        # Log deny
        supabase.table("authorizations").insert({
            "tenant_id": tenant_id, "cost_center_id": req.cost_center,
            "actor_id": req.actor_id, "decision": "DENIED"
        }).execute()
        raise HTTPException(status_code=403, detail=reason)

    # 5. Generar AUT Token
    aut_token = create_aut_token(req.dict())
    
    # 6. Log approval (Async idealmente)
    auth_log = supabase.table("authorizations").insert({
        "tenant_id": tenant_id, "cost_center_id": req.cost_center,
        "actor_id": req.actor_id, "decision": "APPROVED",
        "max_amount": req.max_amount
    }).execute()
    
    return {
        "authorized": True,
        "token": aut_token,
        "auth_id": auth_log.data[0]['id']
    }

@app.post("/v1/receipt")
async def receipt(
    aut_token: str, 
    cost_real: float, 
    metadata: dict
):
    # 1. Validar token (stateless verification)
    try:
        payload = jwt.decode(aut_token, os.getenv("ASARL_SECRET_KEY"), algorithms=["HS256"])
    except:
        raise HTTPException(401, "Invalid AUT Token")
    
    tenant_id = "uuid-del-tenant" # Sacar del payload del token real
    cost_center = payload.get("cost_center")
    
    # 2. Generar firma inmutable
    rx_signature = sign_receipt({"aut": aut_token, "cost": cost_real})
    
    # 3. Guardar Receipt
    supabase.table("receipts").insert({
        "tenant_id": tenant_id,
        "cost_real": cost_real,
        "signature": rx_signature,
        "usage_data": metadata
    }).execute()
    
    # 4. Actualizar contadores (Budget Impact)
    await increment_spend(tenant_id, cost_center, cost_real)
    
    return {"status": "recorded", "receipt_id": rx_signature}