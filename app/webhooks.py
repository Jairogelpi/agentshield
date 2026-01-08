import httpx
from app.db import supabase
import logging

logger = logging.getLogger("agentshield.webhooks")

async def trigger_webhook(tenant_id: str, event_type: str, payload: dict):
    """
    Busca si el cliente tiene un webhook configurado y envía la alerta.
    Fire-and-forget (no bloquea la API).
    """
    # 1. Buscar config activa
    try:
        res = supabase.table("webhooks").select("url, events").eq("tenant_id", tenant_id).execute()
        if not res.data:
            return # No hay webhook configurado

        config = res.data[0]
        if event_type not in config.get("events", []):
            return # El cliente no se suscribió a este evento

        # 2. Enviar alerta (Asíncrono)
        # Usamos un timeout corto para no dejar conexiones colgadas
        async with httpx.AsyncClient() as client:
            await client.post(config['url'], json={
                "event": event_type,
                "timestamp": payload.get("timestamp"),
                "data": payload
            }, timeout=2.0)
    except Exception as e:
        # Log silencioso, no queremos romper el flujo principal
        logger.error(f"Failed to send webhook: {e}")
