from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db import supabase
from app.models import TenantRegion
import secrets
import hashlib

router = APIRouter(tags=["Onboarding"])

class SignupRequest(BaseModel):
    company_name: str
    email: str # Opcional, para contacto
    owner_id: str # UUID de Supabase Auth (Usuario Humano)
    region: TenantRegion = TenantRegion.EU

@router.post("/v1/signup")
async def signup_tenant(req: SignupRequest):
    # 1. Generar API Key única
    raw_key = f"sk_live_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    
    # 2. Crear Tenant en DB
    try:
        res = supabase.table("tenants").insert({
            "name": req.company_name,
            "api_key_hash": key_hash,
            "is_active": True,
            "default_markup": 1.20, # Default margen
            "owner_id": req.owner_id,
            "region": req.region.value
        }).execute()
        
        new_tenant = res.data[0]
        
        # 3. Crear un Centro de Coste por defecto
        default_cc = {
            "tenant_id": new_tenant['id'],
            "name": "Default Project",
            "id": f"cc_{secrets.token_hex(4)}"
        }
        supabase.table("cost_centers").insert(default_cc).execute()
        
        # 3. (Opcional) Crear política por defecto
        default_policy = {
            "limits": {"monthly": 100.0},
            "allowlist": {"models": []}, # Todo permitido
            "mode": "active"
        }
        supabase.table("policies").insert({
            "tenant_id": new_tenant['id'],
            "name": "Default Policy",
            "rules": default_policy
        }).execute()
        
        return {
            "status": "created",
            "tenant_id": new_tenant['id'],
            "api_key": raw_key, # ¡MOSTRAR SOLO UNA VEZ!
            "region": req.region.value,
            "instructions": f"Usa el endpoint de tu región: https://api-{req.region.value}.agentshield.io",
            "message": "Guarda esta clave en lugar seguro. No se volverá a mostrar."
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Signup failed: {str(e)}")
