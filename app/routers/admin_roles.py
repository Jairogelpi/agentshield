from fastapi import APIRouter, Depends, HTTPException, Request
from app.services.role_generator import role_generator
from app.db import supabase
from app.logic import get_current_user_id

router = APIRouter(prefix="/v1/admin/roles", tags=["Admin Roles"])

@router.post("/magic-create")
async def magic_create_role(request: Request, description: str):
    """
    Crea un rol automáticamente a partir de una descripción.
    """
    # 0. Auth Check implicit by Global Guard, but let's get tenant_id context
    # In a real app, we get tenant_id from the user token/session.
    # For now, we mock or fetch from header if available, or query user profile.
    # user_id = get_current_user_id(request)
    # Using a fixed demo tenant for this sprint unless provided in header
    tenant_id = request.headers.get("X-Tenant-ID", "d7a468d0-2620-410a-9d6c-6a4a6b107662") 
    
    # 1. La IA diseña el rol
    new_role = await role_generator.generate_from_description(description, user_id="admin-ai")
    
    # 2. Guardamos en la base de datos (public.role_definitions)
    try:
        res = supabase.table("role_definitions").insert({
            "tenant_id": tenant_id,
            "department": new_role.suggested_department,
            "function": new_role.suggested_function,
            "system_persona": new_role.system_persona,
            "allowed_modes": new_role.allowed_modes,
            "pii_policy": new_role.pii_policy,
            "max_tokens": new_role.max_tokens
        }).execute()
        
        return {"status": "success", "role": res.data}
    except Exception as e:
        # Handles duplication error (Department+Function unique constaint)
        raise HTTPException(status_code=400, detail=str(e))
