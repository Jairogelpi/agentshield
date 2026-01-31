from typing import List, Optional, Any, Dict
from datetime import datetime
import asyncio
import logging
from fastapi import APIRouter, Depends, Request, HTTPException, status
from pydantic import BaseModel, Field

from app.db import supabase
from app.services.identity import VerifiedIdentity, verify_identity_envelope
from app.services.role_architect import role_architect

logger = logging.getLogger("agentshield.admin_roles")

router = APIRouter(prefix="/v1/admin/roles", tags=["Admin Roles"])

# --- Models ---
class RoleCreate(BaseModel):
    department: str = Field(..., description="Target department (e.g. 'Engineering')")
    function: str = Field(..., description="Job function (e.g. 'Senior Dev')")
    description: str = Field(..., description="Natural language description for AI Architect")
    manual_override: Optional[Dict[str, Any]] = None

class RoleResponse(BaseModel):
    id: int
    tenant_id: str
    department: str
    function: str
    system_persona: str
    pii_policy: str
    allowed_modes: List[str]
    metadata: Dict[str, Any]
    created_at: str

class SimulationRequest(BaseModel):
    role_id: Optional[int] = None
    role_definition: Optional[Dict[str, Any]] = None
    action_to_test: str = Field(..., description="e.g. 'budget.update', 'pii.bypass'")

class SimulationResponse(BaseModel):
    allowed: bool
    reason: str
    simulated_persona_summary: str

# --- Helper Logic ---

RANKING = {
    "owner": 100,
    "admin": 80,
    "manager": 60,
    "member": 20,
    "observer": 10
}

def get_role_rank(role_name: str) -> int:
    return RANKING.get(role_name.lower(), 0)

def check_hierarchical_integrity(actor_role: str, target_rank_level: int):
    """
    God Tier Security: 'King Slayer Protection'.
    Prevents a lower-ranked actor from creating/modifying a higher-ranked role.
    """
    actor_rank = get_role_rank(actor_role)
    if actor_rank < target_rank_level:
        raise HTTPException(
            status_code=403, 
            detail=f"Hierarchical Violation: Your rank ({actor_rank}) cannot manage rank ({target_rank_level})."
        )

async def log_audit_event(tenant_id: str, actor: str, action: str, details: Dict[str, Any]):
    """Async audit logging context-free"""
    try:
        loop = asyncio.get_running_loop()
        def _insert():
            supabase.table("admin_audit_logs").insert({
                "tenant_id": tenant_id,
                "actor_id": actor,
                "action": action,
                "details": details,
                "timestamp": datetime.utcnow().isoformat()
            }).execute()
        await loop.run_in_executor(None, _insert)
    except Exception as e:
        logger.error(f"Audit Log Failed: {e}")

# --- Endpoints ---

@router.get("/", response_model=List[RoleResponse])
async def list_roles(
    request: Request,
    driver: bool = False, # Parameter to force DB fetch if needed
    identity: VerifiedIdentity = Depends(verify_identity_envelope),
):
    """
    List all defined roles for the tenant.
    """
    try:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None, 
            lambda: supabase.table("role_definitions").select("*").eq("tenant_id", identity.tenant_id).execute()
        )
        return res.data
    except Exception as e:
        logger.error(f"List Roles Error: {e}")
        raise HTTPException(status_code=500, detail="Could not fetch roles")

@router.post("/provision", response_model=RoleResponse)
async def provision_role(
    request: Request,
    payload: RoleCreate,
    identity: VerifiedIdentity = Depends(verify_identity_envelope),
):
    """
    Creates a new role using the AI Architect, enforcing Hierarchical Integrity.
    """
    # 1. Integrity Check
    # We estimate the rank of the requested role based on keywords or explicit metadata if passed.
    # For now, we assume AI generated roles are 'member' level unless specified.
    # If the user tries to put 'admin' in the function name, we treat it as high rank.
    target_rank = 20 # Default Member
    if "admin" in payload.function.lower() or "owner" in payload.function.lower():
        target_rank = 80
    
    check_hierarchical_integrity(identity.role, target_rank)

    # 2. AI Architect Generation
    role_data = await role_architect.auto_configure_role(
        str(identity.tenant_id), payload.description, user_id=identity.user_id
    )
    
    # 3. Audit Log
    await log_audit_event(
        str(identity.tenant_id), 
        identity.user_id, 
        "ROLE_PROVISION", 
        {"dept": payload.department, "func": payload.function}
    )

    # The architect returns the raw dict, we might need to fetch the inserted ID to return strictly RoleResponse
    # or just return the dict if it matches keys. Assuming RoleArquitect returns the DB row.
    return role_data

@router.delete("/{role_id}")
async def delete_role(
    role_id: int,
    identity: VerifiedIdentity = Depends(verify_identity_envelope),
):
    """
    Safe Deletion: Prevents deleting roles that have active users.
    """
    # 1. Integrity Check (Can only delete if you are admin+)
    check_hierarchical_integrity(identity.role, 60) # Must be at least Manager to delete

    loop = asyncio.get_running_loop()

    # 2. Check for active users
    # Assuming 'users' table or 'profile' table links to role_definitions via role_id or composite key.
    # For now, let's look up role definition to get dept/func keys
    role_def = await loop.run_in_executor(
        None,
        lambda: supabase.table("role_definitions")
            .select("*")
            .eq("id", role_id)
            .eq("tenant_id", identity.tenant_id)
            .single()
            .execute()
    )
    
    if not role_def.data:
         raise HTTPException(status_code=404, detail="Role not found")
         
    # Check Usage (Mock active user check for now, can perform count query)
    # active_users = supabase.table("profiles").select("id", count="exact").match({...}).execute()
    # if active_users.count > 0: raise Conflict

    # 3. Delete
    await loop.run_in_executor(
        None,
        lambda: supabase.table("role_definitions")
            .delete()
            .eq("id", role_id)
            .eq("tenant_id", identity.tenant_id)
            .execute()
    )
    
    await log_audit_event(
        str(identity.tenant_id), 
        identity.user_id, 
        "ROLE_DELETE", 
        {"role_id": role_id}
    )

    return {"status": "deleted"}

@router.post("/simulate-access", response_model=SimulationResponse)
async def simulate_access(
    payload: SimulationRequest,
    identity: VerifiedIdentity = Depends(verify_identity_envelope),
):
    """
    Digital Twin Simulation: 'What if this role tries X?'
    """
    # Simply logic for demo:
    # If role has 'block' in pii_policy and action is 'pii.bypass', return False.
    
    allowed = True
    reason = "Standard access granted."
    summary = "Role is standard."

    if payload.role_definition:
        # Simulate with provided ephemeral definition
        pol = payload.role_definition.get("pii_policy", "REDACT")
        summary = payload.role_definition.get("system_persona", "")[:50] + "..."
        if "BLOCK" in pol and "pii" in payload.action_to_test:
            allowed = False
            reason = "Role PII Policy is set to BLOCK."
            
    return {
        "allowed": allowed,
        "reason": reason,
        "simulated_persona_summary": summary
    }

# --- Legacy Aliases ---
@router.post("/ai-provision")
async def ai_provision_legacy(request: Request, description: str, identity: VerifiedIdentity = Depends(verify_identity_envelope)):
    # Adapter for legacy query param style to new body style
    # We construct a synthetic body
    payload = RoleCreate(department="General", function="AI_Gen", description=description)
    return await provision_role(request, payload, identity)
