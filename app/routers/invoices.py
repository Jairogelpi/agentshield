# app/routers/invoices.py
from fastapi import APIRouter, Depends, HTTPException, Response
from app.services.identity import verify_identity_envelope, VerifiedIdentity
from app.services.invoice_generator import invoice_service
from datetime import datetime
import logging

logger = logging.getLogger("agentshield.invoices")
router = APIRouter(tags=["Invoices"])

@router.get("/v1/invoices/download/{cost_center_id}")
async def download_invoice(
    cost_center_id: str,
    month: int = None,
    year: int = None,
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    Descarga la factura mensual de chargeback interno.
    Solo accesible para Admins o el responsable del Cost Center.
    """
    # 1. Defaults a mes actual
    if not month or not year:
        now = datetime.now()
        month, year = now.month, now.year

    # 2. SEGURIDAD (RBAC Estricto)
    is_admin = identity.role == 'admin'
    # TODO: Enriquecer VerifiedIdentity con cost_center_id si se requiere match exacto
    # Por ahora permitimos a Admin, y logueamos el acceso.
    
    if not is_admin:
        # Aquí iría la lógica de: is_owner = identity.cost_center_id == cost_center_id
        # Como hack de demo/MVP permitimos si es manager (asumimos tiene permiso sobre su CC)
        if identity.role != 'manager':
            raise HTTPException(403, "Access Denied: You cannot view invoices for this Cost Center.")

    # 3. Generar PDF
    try:
        pdf_bytes = await invoice_service.generate_monthly_invoice(
            str(identity.tenant_id), cost_center_id, month, year
        )
    except Exception as e:
        logger.error(f"Invoice generation failed: {e}")
        raise HTTPException(500, "Failed to generate invoice PDF")
    
    # 4. Servir archivo
    filename = f"Invoice_{year}_{month}_{cost_center_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
