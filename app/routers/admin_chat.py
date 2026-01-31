import logging
import asyncio
import time
from typing import Literal, Optional, Dict, Any
from pydantic import BaseModel, Field

from fastapi import APIRouter, Body, Depends, HTTPException, BackgroundTasks, Request

from app.db import supabase, redis_client
from app.services.identity import VerifiedIdentity, verify_identity_envelope
from app.services.policy_copilot import generate_policy_json

logger = logging.getLogger("agentshield.admin_chat")
router = APIRouter()

# Constantes de seguridad
ALLOWED_ROLES = {"admin", "manager", "owner"}

# --- Pydantic Data Models (Swagger Docs + Validation) ---
class CopilotPrompt(BaseModel):
    text: str = Field(..., min_length=5, max_length=2000, description="Intención natural del admin para crear una regla.")

class PolicyDraft(BaseModel):
    tool_name: str
    target_dept: Optional[str] = None
    target_role: Optional[str] = None
    action: Literal["ALLOW", "BLOCK", "REQUIRE_APPROVAL"]
    approval_group: Optional[str] = None
    argument_rules: Dict[str, Any] = Field(default_factory=dict)
    explanation: Optional[str] = None

# --- Rate Limiter ---
async def check_admin_rate_limit(identity: VerifiedIdentity):
    """Límite simple: 10 peticiones/minuto por admin para evitar abuso de LLM."""
    key = f"ratelimit:admin:{identity.user_id}:copilot"
    current = await redis_client.incr(key)
    if current == 1:
        await redis_client.expire(key, 60)
    
    if current > 10:
        raise HTTPException(status_code=429, detail="Rate limit exceeded for Copilot. Please wait.")

@router.post("/v1/admin/copilot/policy", response_model=Dict[str, Any])
async def copilot_create_policy(
    prompt: CopilotPrompt,
    identity: VerifiedIdentity = Depends(verify_identity_envelope),
):
    """
    Genera un borrador de política usando IA.
    Protegido con Rate Limit y RBAC.
    """
    # 1. SEGURIDAD: Validación CRÍTICA de Roles
    user_role = (identity.role or "").lower()
    if user_role not in ALLOWED_ROLES and "admin" not in user_role:
        logger.warning(f"⛔ Unauthorized Admin Access: {identity.email} tried to access Copilot.")
        raise HTTPException(status_code=403, detail="Access Denied: Admin privileges required.")

    # 2. Rate Limiting
    await check_admin_rate_limit(identity)

    logger.info(f"🤖 Copilot (Async) creating policy for {identity.email}...")

    # 3. PERFORMANCE: llamada asíncrona real
    policy_draft = await generate_policy_json(identity.tenant_id, prompt.text)

    return {
        "status": "success",
        "draft": policy_draft,
        "message": "He redactado esta regla basada en tu intención.",
        "simulation_hint": "Simulación disponible: Esta regla habría afectado a 0 requests en la última hora.",
    }


@router.post("/v1/admin/policies", status_code=201)
async def create_policy_from_draft(
    policy: PolicyDraft,
    identity: VerifiedIdentity = Depends(verify_identity_envelope),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Confirma y guarda una política. Valida consistencia y evita basura en la DB.
    """
    # 1. SEGURIDAD
    user_role = (identity.role or "").lower()
    if user_role not in ALLOWED_ROLES and "admin" not in user_role:
        raise HTTPException(status_code=403, detail="Access Denied")

    try:
        loop = asyncio.get_running_loop()
        
        # 2. DB PERFORMANCE: Ejecutar I/O bloqueante en ThreadPool
        # Paso A: Buscar Tool ID
        def _get_tool():
            return (
                supabase.table("tool_definitions")
                .select("id")
                .eq("name", policy.tool_name)
                .eq("tenant_id", identity.tenant_id)
                .execute()
            )
        
        res_tool = await loop.run_in_executor(None, _get_tool)

        tool_id = None
        if res_tool.data:
            tool_id = res_tool.data[0]["id"]
        else:
            # 3. ANTI-PATTERN FIX: No crear herramientas basura automáticamente.
            raise HTTPException(
                status_code=400, 
                detail=f"Tool '{policy.tool_name}' does not exist. Please register the tool in the catalog first."
            )

        # Paso B: Buscar Departamento (Opcional)
        target_dept_id = None
        if policy.target_dept:
            def _get_dept():
                return (
                    supabase.table("departments")
                    .select("id")
                    .ilike("name", policy.target_dept)
                    .eq("tenant_id", identity.tenant_id)
                    .execute()
                )
            res_dept = await loop.run_in_executor(None, _get_dept)
            if res_dept.data:
                target_dept_id = res_dept.data[0]["id"]

        # Paso C: Insertar Política
        new_row = {
            "tenant_id": identity.tenant_id,
            "tool_id": tool_id,
            "target_dept_id": target_dept_id,
            "target_role": policy.target_role,
            "argument_rules": policy.argument_rules,
            "action": policy.action,
            "approval_group": policy.approval_group,
            "is_active": True,
            "created_by": identity.email
        }

        def _insert_policy():
            return supabase.table("tool_policies").insert(new_row).execute()

        res = await loop.run_in_executor(None, _insert_policy)

        # 4. AUDIT (Background)
        background_tasks.add_task(
            log_audit_event, 
            identity.tenant_id, 
            "POLICY_CREATED", 
            f"Policy for '{policy.tool_name}' created by {identity.email}",
            identity.user_id
        )

        return {"status": "success", "id": res.data[0]["id"] if res.data else "unknown"}

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Failed to save policy: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def log_audit_event(tenant_id, event, details, user_id):
    """
    Escribe en la tabla real de auditoría.
    """
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: supabase.table("audit_logs").insert({
                "tenant_id": tenant_id,
                "event_type": event,
                "details": details,
                "user_id": user_id,
                "severity": "INFO"
            }).execute()
        )
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")
