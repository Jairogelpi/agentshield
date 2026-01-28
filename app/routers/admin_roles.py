from fastapi import APIRouter, Depends, Request
from app.services.identity import verify_identity_envelope, VerifiedIdentity
from app.services.role_architect import role_architect

router = APIRouter(prefix="/v1/admin/roles", tags=["Admin Roles"])


@router.post("/ai-provision")
async def ai_provision_role(
    request: Request, 
    description: str,
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    Crea y configura un rol completo usando IA (Role Architect).
    """
    # 0. Auth / Tenant Context
    tenant_id = str(identity.tenant_id)

    # 1. El Arquitecto diseña
    role_data = await role_architect.auto_configure_role(
        tenant_id, description, user_id=identity.user_id
    )

    return {"status": "success", "configured_role": role_data}


@router.post("/magic-create")
async def magic_create_role(request: Request, description: str):
    """
    Legacy endpoint (aliased to AI Provision for backward compat).
    """
    return await ai_provision_role(request, description)
