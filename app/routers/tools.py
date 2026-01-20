# app/routers/tools.py
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from app.db import supabase
from app.services.identity import VerifiedIdentity, verify_identity_envelope

router = APIRouter(tags=["Tools & Governance"])


# --- ESQUEMAS ---
class ApprovalDecision(BaseModel):
    decision: str  # "APPROVED" | "REJECTED"
    reviewer_note: str | None = None


class PolicyDraft(BaseModel):
    # Lo que devuelve el Copilot
    tool_name: str
    target_dept: str | None = None
    target_role: str | None = None
    action: str
    argument_rules: dict[str, Any]
    explanation: str | None = None


# --- ENDPOINTS PARA EL DASHBOARD ---


@router.get("/v1/admin/approvals/pending")
async def get_pending_approvals(identity: VerifiedIdentity = Depends(verify_identity_envelope)):
    """El Dashboard llama aquí para mostrar alertas rojas al jefe."""
    # Permitir admin y manager
    if identity.role not in ["admin", "manager"] and "admin" not in (identity.role or "").lower():
        raise HTTPException(403, "Access denied")

    # Join con tool_definitions para mostrar detalles bonitos si es posible
    # Supabase-py 'select' con foreign keys: select("*, tool_definitions(description)")
    try:
        res = (
            supabase.table("tool_approvals")
            .select("*, tool_definitions(description)")
            .eq("tenant_id", identity.tenant_id)
            .eq("status", "PENDING")
            .execute()
        )
        return res.data
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/v1/admin/approvals/{approval_id}/decide")
async def decide_approval(
    approval_id: str,
    body: ApprovalDecision,
    identity: VerifiedIdentity = Depends(verify_identity_envelope),
):
    """El jefe pulsa 'Aprobar' o 'Rechazar'."""
    if identity.role not in ["admin", "manager"] and "admin" not in (identity.role or "").lower():
        raise HTTPException(403, "Access denied")

    # Validar decisión
    status = body.decision.upper()
    if status not in ["APPROVED", "REJECTED"]:
        raise HTTPException(400, "Invalid decision. Must be APPROVED or REJECTED")

    try:
        # Actualizamos el estado
        res = (
            supabase.table("tool_approvals")
            .update(
                {
                    "status": status,
                    "reviewer_id": identity.user_id,
                    "review_note": body.reviewer_note,
                    "reviewed_at": "now()",
                }
            )
            .eq("id", approval_id)
            .execute()
        )

        return {"status": "updated", "decision": status}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/v1/admin/policies/create")
async def create_policy_from_copilot(
    policy: PolicyDraft, identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """Guarda la política que el Copilot generó y el usuario confirmó."""
    # Relajar chequeo de rol para demo si es necesario, pero idealmente Admin
    if (
        identity.role not in ["admin", "manager", "owner"]
        and "admin" not in (identity.role or "").lower()
    ):
        raise HTTPException(403, "Only admins define policies")

    # 1. Resolver ID de herramienta
    # Buscamos por nombre.
    tool_res = (
        supabase.table("tool_definitions")
        .select("id")
        .eq("name", policy.tool_name)
        .eq("tenant_id", identity.tenant_id)
        .execute()
    )

    tool_id = None
    if tool_res.data:
        tool_id = tool_res.data[0]["id"]
    else:
        # Auto-crear si no existe (Flexibilidad para el Copilot)
        new_tool = (
            supabase.table("tool_definitions")
            .insert(
                {
                    "tenant_id": identity.tenant_id,
                    "name": policy.tool_name,
                    "description": "Auto-registered by Policy Copilot",
                    "risk_level": "MEDIUM",
                }
            )
            .execute()
        )
        if new_tool.data:
            tool_id = new_tool.data[0]["id"]

    if not tool_id:
        raise HTTPException(500, "Failed to resolve tool ID")

    # 2. Resolver ID de departamento (si aplica)
    dept_id = None
    if policy.target_dept:
        dept_res = (
            supabase.table("departments").select("id").ilike("name", policy.target_dept).execute()
        )
        if dept_res.data:
            dept_id = dept_res.data[0]["id"]
        # Si no existe depto, podríamos crearlo o dejarlo NULL (Global/Undefined)
        # Por ahora dejamos NULL si no match para no ensuciar DB de deptos

    # 3. Insertar Política
    try:
        data = {
            "tenant_id": identity.tenant_id,
            "tool_id": tool_id,
            "target_dept_id": dept_id,
            "target_role": policy.target_role,
            "action": policy.action,
            "argument_rules": policy.argument_rules,
            "is_active": True,
        }

        res = supabase.table("tool_policies").insert(data).execute()
        return {"status": "policy_active", "data": res.data}

    except Exception as e:
        raise HTTPException(500, str(e))
