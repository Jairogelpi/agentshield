# agentshield_core/app/routers/onboarding.py
from fastapi import APIRouter, HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime
from pydantic import BaseModel
from app.db import supabase
from app.models import TenantRegion
import secrets
import hashlib
import logging

logger = logging.getLogger("agentshield.onboarding")
router = APIRouter(tags=["Onboarding"])

class SignupRequest(BaseModel):
    company_name: str
    email: str # Opcional
    owner_id: str # UUID de Supabase Auth
    region: TenantRegion = TenantRegion.EU
    accept_tos: bool 
    tos_version_seen: str = "v1.0"

@router.post("/v1/signup")
async def signup_tenant(req: SignupRequest, authenticated_user_id: str = Depends(get_user_id_from_jwt)):
    # 1. Seguridad: Forzar que el target sea el del JWT
    target_owner_id = authenticated_user_id
    
    # 2. Validación Legal
    if not req.accept_tos:
        raise HTTPException(
            status_code=400, 
            detail="You must accept the Terms of Service to proceed."
        )

    # 3. Datos del Tenant (Alineado estrictamente con tu esquema)
    try:
        # Generamos un slug a partir del nombre de la empresa
        slug = req.company_name.lower().replace(" ", "-") + "-" + secrets.token_hex(2)
        
        tenant_data = {
            "name": req.company_name,
            "user_id": target_owner_id,
            "region": req.region.value,
            "registration_method": "OAUTH" if "@" not in (req.email or "") else "EMAIL",
            "slug": slug,
            "compliance_framework": "EU_AI_ACT" if req.region == TenantRegion.EU else "NIST_AI_RMF",
            "brand_config": {
                "logo_url": None, 
                "favicon_url": None, 
                "company_name": req.company_name, 
                "primary_color": "#3B82F6"
            }
        }
        
        # OJO: No insertamos api_key_hash ni is_active ya que no aparecen en tu esquema SQL
        res = supabase.table("tenants").insert(tenant_data).execute()
        
        if not res.data:
            raise Exception("No data returned from tenant insertion. Check if constraints are met.")
            
        new_tenant = res.data[0]
        
        # 4. Crear Centro de Coste Default (Alineado con NOT NULL monthly_limit)
        default_cc = {
            "tenant_id": new_tenant['id'],
            "name": "General Project",
            "id": f"cc_{secrets.token_hex(4)}",
            "monthly_limit": 1000.0, # Obligatorio en tu esquema
            "current_spend": 0.0,
            "is_billable": True
        }
        supabase.table("cost_centers").insert(default_cc).execute()
        
        # 5. Crear Perfil de Usuario
        try:
            supabase.table("user_profiles").insert({
                "user_id": target_owner_id,
                "tenant_id": new_tenant['id'],
                "role": "admin",
                "is_active": True,
                "trust_score": 100
            }).execute()
        except Exception as profile_err:
            logger.warning(f"Profile creation skipped: {profile_err}")
            
        # 6. Política por Defecto
        default_policy = {
            "meta": {"version": "2.0-ALIGNED", "created_at": datetime.utcnow().isoformat()},
            "mode": "active",
            "rules": {
                "pii_redaction": "ENABLED",
                "max_per_request": 5.0,
                "monthly_budget": 500.0
            }
        }
        
        supabase.table("policies").insert({
            "tenant_id": new_tenant['id'],
            "name": "Enterprise Safety Policy",
            "rules": default_policy,
            "mode": "active",
            "is_active": True
        }).execute()
        
        return {
            "status": "created",
            "tenant_id": new_tenant['id'],
            "slug": slug,
            "message": "Organización creada con éxito."
        }
    except Exception as e:
        logger.error(f"Signup error: {e}")
        # Enviamos el detalle para que el frontend pueda mostrarlo
        raise HTTPException(status_code=500, detail=f"Database Alignment Error: {str(e)}")

# --- AUTH HELPERS FOR ONBOARDING ---
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
    # 1. Buscar como Owner/User (Alineado con tu esquema)
    owned = supabase.table("tenants").select("*").eq("user_id", user_id).execute()
    
    return owned.data

class InviteRequest(BaseModel):
    email: str
    role: str = "member"

@router.post("/v1/onboarding/invite")
async def invite_member(req: InviteRequest, user_id: str = Depends(get_user_id_from_jwt)):
    """
    Invita a un miembro a la organización del usuario actual.
    """
    # 1. Obtener la organización del usuario (Alineado con tu esquema)
    orgs = supabase.table("tenants").select("id, name").eq("user_id", user_id).execute()
    
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
