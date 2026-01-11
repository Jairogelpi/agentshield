from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any
from jose import jwt
from app.db import supabase, increment_spend
from app.logic import sign_receipt, SECRET_KEY, ALGORITHM

router = APIRouter()

class ReceiptRequest(BaseModel):
    aut_token: str = Field(..., description="Token JWT de autorización obtenido previamente")
    cost_real: float = Field(..., description="Coste final real de la transacción")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos de uso, tokens, latency, etc.")

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
    auth_id = payload.get("pol") # ID de la autorización original
    function_id = payload.get("fid") # ID de la función (si existe)
    
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
        auth_id=auth_id
    )
    
    return {"status": "recorded", "receipt_id": rx_signature}
