# app/services/billing.py
from app.db import supabase, increment_spend
from app.logic import sign_receipt
import logging

logger = logging.getLogger(__name__)

async def record_transaction(tenant_id: str, cost_center_id: str, cost_real: float, metadata: dict, auth_id: str = None):
    """
    Registra el gasto de una transacción (saving receipt + updating counters).
    Usado tanto por el endpoint /receipt (SDK) como por el Proxy (Server-side).
    """
    # 1. Generar firma
    # Simulamos token si no existe, o firmamos solo los datos clave
    rx_signature = sign_receipt({"tid": tenant_id, "cc": cost_center_id, "cost": cost_real})
    
    # 2. Guardar Receipt
    try:
        trace_id = metadata.get("trace_id")
        supabase.table("receipts").insert({
            "tenant_id": tenant_id,
            "cost_center_id": cost_center_id,
            "cost_real": cost_real,
            "signature": rx_signature,
            "usage_data": metadata,
            "authorization_id": auth_id,
            "trace_id": trace_id
        }).execute()
    except Exception as e:
        logger.error(f"Error saving receipt for tenant {tenant_id}: {e}")
        # Intentamos seguir para cobrar al menos en Redis
        pass
        
    # 3. Actualizar Contadores (Redis + DB)
    await increment_spend(tenant_id, cost_center_id, cost_real)
    
    return rx_signature
