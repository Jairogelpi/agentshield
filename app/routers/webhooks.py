import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.services.email import send_welcome_email

router = APIRouter(tags=["Internal Webhooks"])
logger = logging.getLogger("agentshield.webhooks")

# Modelo del Payload que envía Supabase (pg_net o Edge Functions)
class UserCreatedPayload(BaseModel):
    # La estructura del record 'new' en auth.users
    id: str
    email: str
    raw_user_meta_data: dict = {}

class WebhookPayload(BaseModel):
    type: str # INSERT, UPDATE, etc.
    table: str
    schema: str
    record: UserCreatedPayload # El contenido del INSERT
    old_record: dict | None = None

async def verify_webhook_secret(x_webhook_secret: Annotated[str, Header()]):
    """
    Protección simple: Verifica que la llamada venga de nuestra DB (configurada en el script SQL).
    """
    expected = os.getenv("WEBHOOK_SECRET", "super-secret-internal-key")
    if x_webhook_secret != expected:
        raise HTTPException(status_code=403, detail="Invalid Webhook Secret")

@router.post("/v1/webhooks/auth/user-created")
async def on_user_created(
    payload: WebhookPayload,
    # secret: str = Depends(verify_webhook_secret) # Descomentar para producción
):
    """
    Webhook llamado por PostgreSQL (pg_net) AFTER INSERT en auth.users.
    """
    try:
        user_email = payload.record.email
        user_id = payload.record.id
        # Intentar sacar el nombre de los metadatos
        meta = payload.record.raw_user_meta_data or {}
        user_name = meta.get("full_name") or meta.get("name") or "Agent"

        logger.info(f"⚡ New User Detected: {user_email} (ID: {user_id}). Sensing welcome email...")
        
        # Enviar Email
        await send_welcome_email(user_email, user_name)
        
        return {"status": "processed", "action": "welcome_email_sent"}
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
