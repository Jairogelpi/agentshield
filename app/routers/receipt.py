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
    
    if not tenant_id or not cost_center:
         raise HTTPException(status_code=400, detail="Malformed Token Payload")

    # 2. Generar firma inmutable
    # Esto asegura que el recibo no ha sido alterado desde que el SDK lo envió
    rx_signature = sign_receipt({"aut": req.aut_token, "cost": req.cost_real})
    
    # 3. Guardar Receipt en Supabase
    try:
        supabase.table("receipts").insert({
            "tenant_id": tenant_id,
            "cost_center_id": cost_center,
            "cost_real": req.cost_real,
            "signature": rx_signature,
            "usage_data": req.metadata,
            "authorization_id": auth_id
        }).execute()
    except Exception as e:
        # Log error pero no romper si ya se procesó.
        # En diseño robusto deberíamos tener cola de reintentos.
        print(f"Error saving receipt: {e}")
        # Si falla guardar el recibo, ¿debemos cobrar? 
        # Sí, el gasto existió. Intentamos incrementar spend.
    
    # 4. Actualizar contadores (Budget Impact)
    # Esto actualiza Redis y DB atómicamente
    await increment_spend(tenant_id, cost_center, req.cost_real)
    
    return {"status": "recorded", "receipt_id": rx_signature}
