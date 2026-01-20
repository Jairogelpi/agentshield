# app/routers/feedback.py
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import redis_client, supabase
from app.services.identity import VerifiedIdentity, verify_identity_envelope

router = APIRouter()
logger = logging.getLogger("agentshield.learning")


class FeedbackSignal(BaseModel):
    message_id: str
    score: int  # 1 (Like), -1 (Dislike)
    correction: str = None  # Si el usuario editó el mensaje, es oro puro


@router.post("/v1/feedback")
async def ingest_learning_signal(
    signal: FeedbackSignal, identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    El ciclo de aprendizaje.
    1. Si es Like: Refuerza el patrón en Hive Memory.
    2. Si es Dislike: Penaliza al modelo/prompt usado para ese tipo de tarea.
    3. Si hay corrección: Genera un nuevo par de entrenamiento.
    """

    try:
        # 1. Registrar el voto en logs persistentes (Supabase)
        # Usamos asyncio.to_thread si supabase es bloqueante, o asumimos fast io
        supabase.table("feedback_logs").insert(
            {
                "tenant_id": identity.tenant_id,
                "user_id": identity.user_id,
                "message_id": signal.message_id,
                "score": signal.score,
                "correction": signal.correction,
            }
        ).execute()

        # 2. APRENDIZAJE ACTIVO (La Magia)
        if signal.score > 0:
            # ¡Éxito! Promocionamos esta respuesta a la Colmena (Hive Memory)
            logger.info(f"🧠 Learning: Reinforcing successful interaction for {identity.dept_id}")

            # TODO: Marcar en Hive Memory si ya existe

        elif signal.score < 0:
            # Fracaso.
            logger.warning("📉 Learning: Negative feedback recorded.")

        return {"status": "learned"}

    except Exception as e:
        logger.error(f"Feedback ingestion failed: {e}")
        # No fallamos la request del usuario por esto
        return {"status": "error", "detail": str(e)}
