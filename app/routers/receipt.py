import io
import json
import zipfile
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from fpdf import FPDF

from app.db import increment_spend, supabase
from app.logic import ALGORITHM, SECRET_KEY, sign_receipt

router = APIRouter()


class ReceiptRequest(BaseModel):
    aut_token: str = Field(..., description="Token JWT de autorización obtenido previamente")
    cost_real: float = Field(..., description="Coste final real de la transacción")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Metadatos de uso, tokens, latency, etc."
    )


@router.post("/v1/receipt")
async def receipt(req: ReceiptRequest):
    # 1. Validar token (stateless verification)
    try:
        # Usamos app.logic.SECRET_KEY para decodificar
        payload = jwt.decode(req.aut_token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid AUT Token: {str(e)}")

    # Extraer info del token
    # payload example: {"sub": "actor", "tid": "tenant", "cc": "cost_center", ...}
    tenant_id = payload.get("tid")
    cost_center = payload.get("cc")
    auth_id = payload.get("pol")  # ID de la autorización original
    function_id = payload.get("fid")  # ID de la función (si existe)

    if not tenant_id or not cost_center:
        raise HTTPException(status_code=400, detail="Malformed Token Payload")

    # Inyectar function_id en metadata para que el worker lo procese
    if function_id:
        req.metadata["function_id"] = function_id

    # 2. Delegar en Servicio de Facturación
    # Esto maneja la firma, la inserción en DB y la actualización de Redis
    from app.services.billing import record_transaction

    rx_signature = await record_transaction(
        tenant_id=tenant_id,
        cost_center_id=cost_center,
        cost_real=req.cost_real,
        metadata=req.metadata,
        auth_id=auth_id,
    )

    return {"status": "recorded", "receipt_id": rx_signature}


@router.post("/v1/evidence/package")
async def generate_legal_discovery_package(receipt_id: str):
    """
    The Black Box: Generates a self-contained forensic ZIP for legal discovery.
    """
    # 1. Fetch receipt data from DB
    res = (
        supabase.table("receipts")
        .select("*")
        .eq("id", receipt_id)
        .single()
        .execute()
    )
    
    if not res.data:
        raise HTTPException(status_code=404, detail="Receipt not found")
        
    receipt = res.data
    content = receipt.get("content_json") or {}
    signature = receipt.get("signature")
    
    # 2. Generate PDF Transcript
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(40, 10, "AgentShield Forensic Transcript")
    pdf.ln(20)
    
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 10, f"Receipt ID: {receipt_id}", ln=True)
    pdf.cell(0, 10, f"Timestamp: {content.get('timestamp')}", ln=True)
    pdf.cell(0, 10, f"Tenant: {content.get('tenant_id')}", ln=True)
    pdf.cell(0, 10, f"Actor: {content.get('actor')}", ln=True)
    pdf.ln(10)
    
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Transaction Details:", ln=True)
    pdf.set_font("Arial", "", 10)
    
    tx = content.get("transaction", {})
    for k, v in tx.items():
        pdf.cell(0, 10, f"{k}: {v}", ln=True)
        
    pdf_buffer = io.BytesIO()
    pdf_output = pdf.output()
    if isinstance(pdf_output, bytearray):
        pdf_buffer.write(pdf_output)
    else:
        pdf_buffer.write(bytes(pdf_output, 'latin1'))
    pdf_buffer.seek(0)

    # 3. Get Public Key from Secure Service
    from app.services.crypto_signer import get_public_key_pem
    public_key = get_public_key_pem()

    # 4. Load Verification Tool Template
    tool_content = "<html>Verification Tool Not Found</html>"
    try:
        import os
        template_path = "app/templates/verification_tool.html"
        if os.path.exists(template_path):
            with open(template_path, "r", encoding="utf-8") as f:
                tool_content = f.read()
    except:
        pass

    # 5. Bundle everything into a ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # HUMAN READABLE
        zip_file.writestr("chat_transcript.pdf", pdf_buffer.getvalue())
        
        # MACHINE READABLE
        zip_file.writestr("transcript.json", json.dumps(content, indent=2))
        
        # CRYPTOGRAPHIC PROOF
        zip_file.writestr("digital_signature.sig", signature)
        zip_file.writestr("public_key.pem", public_key)
        
        # OFFLINE TOOL
        zip_file.writestr("verification_tool.html", tool_content)
        
    zip_buffer.seek(0)
    
    filename = f"evidence_{receipt_id[:8]}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
