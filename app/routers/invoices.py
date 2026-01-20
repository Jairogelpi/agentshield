# app/routers/invoices.py
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response

from app.services.identity import VerifiedIdentity, verify_identity_envelope
from app.services.invoice_generator import generate_department_invoice_pdf
from app.services.invoice_service import compute_invoice

logger = logging.getLogger("agentshield.invoices")
router = APIRouter(tags=["Invoices"])


@router.get("/v1/invoices/download/{cost_center_id}")
async def download_invoice(
    cost_center_id: str,
    month: str = None,  # Formato YYYY-MM
    identity: VerifiedIdentity = Depends(verify_identity_envelope),
):
    """
    Descarga la factura mensual de chargeback interno con control de acceso estricto.
    """
    # 1. Validar Mes
    if not month:
        month = datetime.utcnow().strftime("%Y-%m")

    # 2. SEGURIDAD (Record-Level ACL)
    is_admin = identity.role == "admin"
    # TODO: En un sistema real, el token JWT vendría con los cost_centers permitidos
    # Para el MVP, permitimos si el usuario es manager del tenant o admin global.
    if not is_admin and identity.role != "manager":
        raise HTTPException(
            403, "Access Denied: High-privilege access required for financial documents."
        )

    # 3. Agregación de Datos Computados
    try:
        invoice_data = await compute_invoice(str(identity.tenant_id), cost_center_id, month)
    except Exception as e:
        logger.error(f"Invoice computation failed for {cost_center_id}: {e}")
        raise HTTPException(500, "Financial data aggregation failed.")

    # 4. Generación de PDF Criptográfico
    try:
        pdf_bytes = generate_department_invoice_pdf(invoice_data)
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        raise HTTPException(500, "Invoice rendering engine error.")

    filename = f"Invoice_{cost_center_id}_{month}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
