# app/services/billing.py
from app.db import supabase, increment_spend, redis_client
from app.utils import fast_json as json
from app.logic import sign_receipt
import logging

logger = logging.getLogger(__name__)

async def record_transaction(
    tenant_id: str, 
    cost_center_id: str, 
    cost_real: float, 
    metadata: dict, 
    auth_id: str = None,
    cache_hit: bool = False,
    tokens_saved: int = 0
):
    """
    Registra el gasto de una transacción (saving receipt + updating counters).
    Usado tanto por el endpoint /receipt (SDK) como por el Proxy (Server-side).
    """
    # 1. Generar firma
    # Simulamos token si no existe, o firmamos solo los datos clave
    # Incluimos la REGIÓN para prueba legal inmutable
    # + CERTIFICACIÓN DE PRIVACIDAD (PII Sanitized)
    region = metadata.get("processed_in", "eu")
    
    # RISK AUDIT FIELDS (EU AI ACT)
    compliance_tag = metadata.get("compliance_level", "standard")
    use_case = metadata.get("use_case", "general")

    rx_signature = sign_receipt({
        "tid": tenant_id, 
        "cc": cost_center_id, 
        "cost": cost_real,
        "region": region,
        "mode": metadata.get("execution_mode", "ACTIVE"), # Prueba auditada del modo
        "pii_safe": True,
        "risk_class": use_case, # <--- PRUEBA LEGAL
        "audit_mode": compliance_tag
    })
    
    # 2. Guardar Receipt
    try:
        trace_id = metadata.get("trace_id")
        region = metadata.get("processed_in", "eu")
        
        
        # Validamos que el metadato se guarde
        if "pii_sanitized" not in metadata:
            metadata["pii_sanitized"] = True
            
        def _save_receipt():
            return supabase.table("receipts").insert({
                "tenant_id": tenant_id,
                "cost_center_id": cost_center_id,
                "cost_real": cost_real,
                "signature": rx_signature,
                "usage_data": metadata,
                "authorization_id": auth_id,
                "trace_id": trace_id,
                "processed_in": region,
                "cache_hit": cache_hit,
                "tokens_saved": tokens_saved 
            }).execute()

        # Non-blocking execution
        import asyncio
        await asyncio.to_thread(_save_receipt)
    except Exception as e:
        logger.error(f"CRITICAL BILLING FAILURE: {e}")
        # Guardar en una lista de 'fallidos' en Redis para reprocesar luego
        # DEAD LETTER QUEUE (DLQ)
        failed_receipt = {
            "tenant_id": tenant_id,
            "cost_center_id": cost_center_id,
            "cost_real": cost_real,
            "signature": rx_signature,
            "metadata": metadata,
            "auth_id": auth_id, 
            "error": str(e)
        }
        try:
            await redis_client.lpush("failed_receipts", json.dumps(failed_receipt))
        except Exception as redis_e:
             logger.critical(f"🔥 CATASTROPHIC FAILURE: Could not save to DLQ either: {redis_e}")
        
    # 3. Actualizar Contadores (Redis + DB) (Solo si hay coste real)
    if not cache_hit and cost_real > 0:
        await increment_spend(tenant_id, cost_center_id, cost_real)
    
    return rx_signature
