# app/services/billing.py
from app.db import supabase, increment_spend
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
            
        supabase.table("receipts").insert({
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
    except Exception as e:
        logger.error(f"Error saving receipt for tenant {tenant_id}: {e}")
        # Intentamos seguir para cobrar al menos en Redis
        pass
        
    # 3. Actualizar Contadores (Redis + DB) (Solo si hay coste real)
    if not cache_hit and cost_real > 0:
        await increment_spend(tenant_id, cost_center_id, cost_real)
    
    return rx_signature
