import logging
import asyncio
from fastapi import APIRouter, Body, Depends, HTTPException, BackgroundTasks

from app.db import supabase
from app.services.identity import VerifiedIdentity, verify_identity_envelope
from app.services.policy_copilot import generate_policy_json

logger = logging.getLogger("agentshield.admin_chat")
router = APIRouter()

# Constantes de seguridad
ALLOWED_ROLES = {"admin", "manager", "owner"}

@router.post("/v1/admin/copilot/policy")
async def copilot_create_policy(
    prompt: dict = Body(...),
    identity: VerifiedIdentity = Depends(verify_identity_envelope),
):
    """
    Genera un borrador de política usando IA. NO bloquea el Event Loop.
    """
    # 1. SEGURIDAD: Validación CRÍTICA de Roles
    user_role = (identity.role or "").lower()
    if user_role not in ALLOWED_ROLES and "admin" not in user_role:
        logger.warning(f"⛔ Unauthorized Admin Access: {identity.email} tried to access Copilot.")
        raise HTTPException(status_code=403, detail="Access Denied: Admin privileges required.")

    text = prompt.get("text")
    if not text:
        raise HTTPException(status_code=400, detail="Prompt text required")

    logger.info(f"🤖 Copilot (Async) creating policy for {identity.email}...")

    # 2. PERFORMANCE: llamada asíncrona real
    # generate_policy_json ahora usa 'acompletion' internamente
    policy_draft = await generate_policy_json(identity.tenant_id, text)

    return {
        "status": "success",
        "draft": policy_draft,
        "message": "He redactado esta regla basada en tu intención.",
        "simulation_hint": "Simulación disponible: Esta regla habría afectado a 0 requests en la última hora.",
    }


@router.post("/v1/admin/policies")
async def create_policy_from_draft(
    policy: dict = Body(...), 
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

    # 2. VALIDACIÓN
    required = ["action", "tool_name"]
    if not all(k in policy for k in required):
        raise HTTPException(status_code=400, detail="Invalid policy format: Missing 'action' or 'tool_name'")

    try:
        loop = asyncio.get_running_loop()
        
        # 3. DB PERFORMANCE: Ejecutar I/O bloqueante en ThreadPool
        # Paso A: Buscar Tool ID
        def _get_tool():
            return (
                supabase.table("tool_definitions")
                .select("id")
                .eq("name", policy["tool_name"])
                .eq("tenant_id", identity.tenant_id)
                .execute()
            )
        
        res_tool = await loop.run_in_executor(None, _get_tool)

        tool_id = None
        if res_tool.data:
            tool_id = res_tool.data[0]["id"]
        else:
            # 4. ANTI-PATTERN FIX: No crear herramientas basura automáticamente.
            # Fail fast obliga a mantener un catálogo limpio.
            raise HTTPException(
                status_code=400, 
                detail=f"Tool '{policy['tool_name']}' does not exist. Please register the tool in the catalog first."
            )

        # Paso B: Buscar Departamento (Opcional)
        target_dept_id = None
        if policy.get("target_dept"):
            def _get_dept():
                return (
                    supabase.table("departments")
                    .select("id")
                    .ilike("name", policy["target_dept"])
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
            "target_role": policy.get("target_role"),
            "argument_rules": policy.get("argument_rules", {}),
            "action": policy["action"],
            "approval_group": policy.get("approval_group"),
            "is_active": True,
            "created_by": identity.email
        }

        def _insert_policy():
            return supabase.table("tool_policies").insert(new_row).execute()

        res = await loop.run_in_executor(None, _insert_policy)

        # 5. SIMULATION / AUDIT (Background)
        # En background, podríamos recalcular métricas o invalidar caché
        background_tasks.add_task(log_audit_event, identity.tenant_id, "POLICY_CREATED", f"Policy for {policy['tool_name']} created by {identity.email}")

        return {"status": "success", "id": res.data[0]["id"] if res.data else "unknown"}

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Failed to save policy: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def log_audit_event(tenant_id, event, details):
    # Stub para auditoría futura
    logger.info(f"[AUDIT] {tenant_id} - {event}: {details}")
