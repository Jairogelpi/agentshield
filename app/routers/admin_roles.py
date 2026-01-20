from fastapi import APIRouter, Request, Depends
from app.services.role_architect import role_architect

router = APIRouter(prefix="/v1/admin/roles", tags=["Admin Roles"])

@router.post("/ai-provision")
async def ai_provision_role(request: Request, description: str):
    """
    Crea y configura un rol completo usando IA (Role Architect).
    """
    # 0. Auth / Tenant Context
    # En prod: identity = Depends(verify_identity_envelope)
    # Mocking tenant for demo velocity
    tenant_id = request.headers.get("X-Tenant-ID", "d7a468d0-2620-410a-9d6c-6a4a6b107662") 
    
    # 1. El Arquitecto diseña
    role_data = await role_architect.auto_configure_role(tenant_id, description, user_id="admin-gui")
    
    return {"status": "success", "configured_role": role_data}

@router.post("/magic-create")
async def magic_create_role(request: Request, description: str):
    """
    Legacy endpoint (aliased to AI Provision for backward compat).
    """
    return await ai_provision_role(request, description)
