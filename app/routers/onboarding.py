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
    email: str # Opcional, para contacto
    owner_id: str # UUID de Supabase Auth (Usuario Humano)
    region: TenantRegion = TenantRegion.EU
    # CAMBIO: Campo obligatorio. Si el frontend no lo manda True, falla.
    accept_tos: bool 
    tos_version_seen: str = "v1.0" # La versión que el usuario vio en el frontend

@router.post("/v1/signup")
async def signup_tenant(req: SignupRequest):
    # 2. Validación Legal (Gatekeeper)
    if not req.accept_tos:
        raise HTTPException(
            status_code=400, 
            detail="You must accept the Terms of Service (including Shadow Mode liability clauses) to proceed."
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
            "default_markup": 1.20, # Default margen
            "owner_id": req.owner_id,
            "region": req.region.value,
            # DATOS LEGALES VINCULANTES
            "tos_accepted": True,
            "tos_accepted_at": datetime.utcnow().isoformat(),
            "tos_version": req.tos_version_seen
        }).execute()
        
        new_tenant = res.data[0]
        
        # 3. Crear un Centro de Coste por defecto
        default_cc = {
            "tenant_id": new_tenant['id'],
            "name": "Default Project",
            "id": f"cc_{secrets.token_hex(4)}"
        }
        supabase.table("cost_centers").insert(default_cc).execute()
        
        # 3. POLÍTICA "SECURE BY DEFAULT" (Blindaje Legal)
        # El modo es 'active' (BLOQUEANTE) por defecto.
        # Shadow Mode debe ser activado manualmente por el cliente asumiendo el riesgo.
        default_policy = {
            "meta": {
                "version": "1.0",
                "created_at": "now()",
                "description": "Default Safety Policy"
            },
            "mode": "active", # <--- CRÍTICO: Bloquea si se supera el límite
            "panic_mode": False,
            "limits": {
                "monthly": 50.0, # Límite inicial bajo (50€) para evitar sorpresas
                "per_request": 2.0, # Ninguna request simple debería costar más de 2€
                "actors": {} # Sin excepciones por usuario
            },
            "allowlist": {
                # Por seguridad, solo permitimos modelos "baratos/seguros" al inicio.
                # El cliente debe añadir GPT-4 explícitamente si lo quiere.
                "models": ["gpt-3.5-turbo", "gpt-4o-mini", "claude-3-haiku"],
                "providers": ["openai", "anthropic", "groq"]
            },
            "governance": {
                # Cualquier gasto único > 5€ requiere aprobación humana
                "require_approval_above_cost": 5.0 
            },
            "smart_routing": {
                "enabled": False # Routing apagado para evitar comportamientos "magicos" no solicitados
            }
        }
        
        # Insertamos esta política robusta
        supabase.table("policies").insert({
            "tenant_id": new_tenant['id'],
            "name": "Default Safety Policy",
            "rules": default_policy,
            "mode": "active", # Redundancia en columna SQL para búsquedas rápidas
            "is_active": True
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
