# agentshield_core/app/routers/onboarding.py
from fastapi import APIRouter, HTTPException
from datetime import datetime
from pydantic import BaseModel
from app.db import supabase
from app.models import TenantRegion
import secrets
import hashlib

router = APIRouter(tags=["Onboarding"])

class SignupRequest(BaseModel):
    company_name: str
    email: str # Opcional
    owner_id: str # UUID de Supabase Auth
    region: TenantRegion = TenantRegion.EU
    accept_tos: bool 
    tos_version_seen: str = "v1.0"

@router.post("/v1/signup")
async def signup_tenant(req: SignupRequest):
    # 2. Validación Legal
    if not req.accept_tos:
        raise HTTPException(
            status_code=400, 
            detail="You must accept the Terms of Service to proceed."
        )

    # 1. Generar API Key única
    raw_key = f"sk_live_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    
    # 2. Crear Tenant en DB
    try:
        res = supabase.table("tenants").insert({
            "name": req.company_name,
            "api_key_hash": key_hash,
            "is_active": True,
            "default_markup": 1.20,
            "owner_id": req.owner_id,
            "region": req.region.value,
            "tos_accepted": True,
            "tos_accepted_at": datetime.utcnow().isoformat(),
            "tos_version": req.tos_version_seen
        }).execute()
        
        new_tenant = res.data[0]
        
        # 3. Crear Centro de Coste Default
        default_cc = {
            "tenant_id": new_tenant['id'],
            "name": "Default Project",
            "id": f"cc_{secrets.token_hex(4)}"
        }
        supabase.table("cost_centers").insert(default_cc).execute()
        
        # 4. Política Default
        default_policy = {
            "meta": {"version": "2.0-EU-COMPLIANT", "created_at": "now()"},
            "mode": "active",
            "panic_mode": False,
            "risk_management": {
                "rules": {
                    "biometric_id": "PROHIBITED",
                    "hr_recruitment": "HUMAN_CHECK",
                    "medical_advice": "HUMAN_CHECK",
                    "credit_scoring": "LOG_AUDIT",
                    "general_purpose": "ALLOW"
                }
            },
            "limits": {"monthly": 50.0, "per_request": 2.0, "actors": {}},
            "allowlist": {
                "models": ["gpt-3.5-turbo", "gpt-4o-mini", "claude-3-haiku"],
                "providers": ["openai", "anthropic", "groq"]
            },
            "governance": {"require_approval_above_cost": 5.0},
            "smart_routing": {"enabled": False}
        }
        
        supabase.table("policies").insert({
            "tenant_id": new_tenant['id'],
            "name": "Default Safety Policy",
            "rules": default_policy,
            "mode": "active",
            "is_active": True
        }).execute()
        
        return {
            "status": "created",
            "tenant_id": new_tenant['id'],
            "api_key": raw_key,
            "region": req.region.value,
            # CORRECCIÓN AQUÍ: Usamos tu nuevo dominio
            "instructions": "Usa tu endpoint seguro: https://getagentshield.com",
            "message": "Guarda esta clave en lugar seguro."
        }
        

# --- AUTH HELPERS FOR ONBOARDING ---
from fastapi import Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
security = HTTPBearer()

async def get_user_id_from_jwt(credentials: HTTPAuthorizationCredentials = Security(security)):
    """
    Valida el token pero NO requiere tener un tenant asociado.
    """
    token = credentials.credentials
    try:
        user_response = supabase.auth.get_user(token)
        return user_response.user.id
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid Session")

@router.get("/v1/onboarding/organizations")
async def list_my_organizations(user_id: str = Depends(get_user_id_from_jwt)):
    """
    Devuelve la lista de organizaciones donde el usuario es Owner o Miembro.
    """
    # 1. Buscar como Owner
    owned = supabase.table("tenants").select("*").eq("owner_id", user_id).execute()
    
    # 2. Buscar como Miembro (TODO: Implementar tabla 'tenant_members')
    # Por ahora solo soportamos Owner para el MVP
    
    return owned.data

class InviteRequest(BaseModel):
    email: str
    role: str = "member"

@router.post("/v1/onboarding/invite")
async def invite_member(req: InviteRequest, user_id: str = Depends(get_user_id_from_jwt)):
    """
    Invita a un miembro a la organización del usuario actual.
    """
    # 1. Obtener la organización del usuario (Asumimos la primera que tenga como Owner para MVP)
    # En el futuro, el frontend debería enviar el tenant_id contextualmente.
    orgs = supabase.table("tenants").select("id, name").eq("owner_id", user_id).execute()
    
    if not orgs.data:
        raise HTTPException(status_code=400, detail="You need to create an organization first.")
        
    tenant = orgs.data[0]
    
    # 2. (Simulación) Enviar Email
    # Aquí iría la lógica de `resend` o `sendgrid`
    # Por ahora solo insertamos en una tabla de 'invites' si existiera, o devolvemos OK
    
    # Simulated response
    return {
        "status": "invited",
        "email": req.email,
        "tenant_id": tenant['id'],
        "tenant_name": tenant['name'],
        "message": f"Invitation sent to {req.email}"
    }
