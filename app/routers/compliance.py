from fastapi import APIRouter, Depends, HTTPException
from app.services.identity import verify_identity_envelope, VerifiedIdentity
from app.services.compliance import compliance_officer
from app.db import supabase

router = APIRouter(tags=["Compliance Center"])

@router.post("/v1/compliance/forget-user")
async def forget_user(
    target_user_id: str,
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    Ejecuta el protocolo 'Derecho al Olvido' (Right to be Forgotten).
    Mata la PII pero salva los libros contables.
    """
    # Solo DPO o Admin pueden ejecutar borrados masivos
    if identity.role not in ['admin', 'dpo']:
        raise HTTPException(status_code=403, detail="Privileged Action: Only DPO or Admin can purge user data.")
        
    result = await compliance_officer.execute_right_to_forget(
        str(identity.tenant_id), 
        target_user_id,
        identity.user_id
    )
    
    return {
        "status": "success",
        "action": "ANONYMIZATION",
        "certificate": result
    }

@router.post("/v1/compliance/audit-snapshot")
async def create_audit_snapshot(
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """Genera un informe instantáneo de cumplimiento (AI Act Ready)."""
    if identity.role not in ['admin', 'auditor', 'dpo']:
        raise HTTPException(status_code=403, detail="Access Denied")
        
    result = await compliance_officer.generate_system_snapshot(
        str(identity.tenant_id),
        identity.user_id
    )
    
    return {
        "status": "generated",
        "certificate": result
    }

@router.get("/v1/compliance/history")
async def get_compliance_history(
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """Devuelve el historial de auditoría y links a certificados."""
    res = supabase.table("compliance_actions")\
        .select("*, compliance_certificates(storage_path, valid_until)")\
        .eq("tenant_id", identity.tenant_id)\
        .order("created_at", desc=True)\
        .execute()
    return res.data

@router.post("/v1/compliance/report")
async def generate_compliance_report(
    framework: str = "GDPR",
    days: int = 30,
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    Genera un PDF legal oficial (Evidence-Based Reporting).
    """
    if identity.role not in ['admin', 'dpo', 'auditor']:
         raise HTTPException(status_code=403, detail="Only DPO/Admin can generate legal certificates.")

    from app.services.compliance_reporter import compliance_reporter
    from fastapi.responses import Response

    try:
        pdf_bytes = await compliance_reporter.generate_audit_report(
            str(identity.tenant_id),
            framework,
            days
        )
        
        filename = f"Compliance_Certificate_{framework}_{identity.tenant_id[:8]}.pdf"
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")

@router.get("/v1/quarantine/pending")
async def get_quarantine_queue(
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """Lista los archivos en cuarentena para revisión humana."""
    if identity.role not in ['admin', 'dpo', 'security_analyst']:
        raise HTTPException(status_code=403, detail="Privileged Action")
        
    res = supabase.table("quarantine_queue")\
        .select("*")\
        .eq("tenant_id", identity.tenant_id)\
        .eq("status", "PENDING")\
        .order("created_at", desc=True)\
        .execute()
        
    return res.data or []

@router.post("/v1/quarantine/{quarantine_id}/resolve")
async def resolve_quarantine(
    quarantine_id: str,
    decision: str = "APPROVE", # 'APPROVE' or 'REJECT'
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    HITL: Humano resuelve la duda de la IA.
    Active Learning: Si aprueba, el hash entra en Whitelist.
    """
    if identity.role not in ['admin', 'dpo', 'security_analyst']:
        raise HTTPException(status_code=403, detail="Privileged Action")

    # 1. Obtener Item de Cuarentena
    res = supabase.table("quarantine_queue").select("*").eq("id", quarantine_id).maybe_single().execute()
    item = res.data
    
    if not item:
        raise HTTPException(404, "Quarantine item not found")

    if item['tenant_id'] != str(identity.tenant_id):
        raise HTTPException(403, "Access Denied")

    if decision == "APPROVE":
        # A. WHITELIST (Active Learning)
        # La próxima vez, la latencia será 0ms.
        try:
            supabase.table("semantic_whitelist").insert({
               "tenant_id": item['tenant_id'],
               "file_hash": item['file_hash'],
               "approved_by": identity.user_id,
               "reason": "Manual Approval (HITL)"
            }).execute()
        except Exception as e:
            # Puede ser duplicado, ignoramos
            pass
            
        new_status = "APPROVED"
        msg = "File whitelisted. Active learning updated."
    else:
        new_status = "REJECTED"
        msg = "File rejection confirmed. Threat neutralized."

    # 2. Actualizar Estado Cola
    supabase.table("quarantine_queue").update({
        "status": new_status,
        "admin_feedback_notes": f"Resolved by {identity.user_id} at {datetime.now()}"
    }).eq("id", quarantine_id).execute()

    return {"status": "success", "message": msg, "action": new_status}
