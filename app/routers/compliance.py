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
