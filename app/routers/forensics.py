# app/routers/forensics.py
from fastapi import APIRouter, Depends, Response, HTTPException
from app.services.identity import verify_identity_envelope, VerifiedIdentity
from app.services.forensics import forensics
import logging

router = APIRouter(tags=["Forensics & Audit"])
logger = logging.getLogger("agentshield.forensics")

@router.get("/v1/audit/replay/{trace_id}")
async def get_incident_replay(
    trace_id: str,
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    Recupera la "Caja Negra" de una transacción específica.
    Solo para roles privilegiados o dueños del tenant.
    """
    # Seguridad básica: Solo Admin/CISO o el dueño del tenant
    # (Aquí simplificamos comprobando tenant_id, en prod checking el rol también)
    
    logger.info(f"🕵️ Forensic Replay requested for {trace_id} by {identity.email}")
    
    timeline = await forensics.reconstruct_timeline(identity.tenant_id, trace_id)
    return {"trace_id": trace_id, "timeline": timeline}

@router.get("/v1/audit/replay/{trace_id}/export")
async def export_incident_pdf(
    trace_id: str,
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    Genera y descarga un PDF legalmente admisible con la cadena de custodia.
    """
    logger.info(f"📄 Forensic PDF Export requested for {trace_id} by {identity.email}")
    
    timeline = await forensics.reconstruct_timeline(identity.tenant_id, trace_id)
    
    if not timeline:
        raise HTTPException(404, "Trace ID not found or partial data missing.")
        
    try:
        pdf_bytes = forensics.generate_legal_pdf(timeline, trace_id)
    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        raise HTTPException(500, f"PDF Generation Error: {str(e)}")
    
    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=forensic_{trace_id}.pdf"}
    )
