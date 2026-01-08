# app/routers/compliance.py
# GDPR Right to Erasure (Article 17) - Derecho al Olvido
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from app.db import supabase
from app.routers.authorize import get_tenant_from_jwt as get_current_tenant_id
from opentelemetry import trace
import logging

router = APIRouter(prefix="/v1/compliance", tags=["GDPR Compliance"])
tracer = trace.get_tracer(__name__)
logger = logging.getLogger("agentshield.gdpr")

class ForgetRequest(BaseModel):
    actor_id: str
    reason: str = "GDPR Right to Erasure request"

@router.post("/forget-user")
async def forget_user(
    req: ForgetRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_current_tenant_id)
):
    """
    Ejecuta el 'Derecho al Olvido' (RGPD Art. 17).
    Anonimiza irreversiblemente toda la actividad histórica de un usuario.
    Mantiene los totales financieros para contabilidad.
    """
    with tracer.start_as_current_span("gdpr_forget_user") as span:
        span.set_attribute("tenant.id", tenant_id)
        span.set_attribute("gdpr.reason", req.reason)
        # No logueamos el actor_id para no crear más PII en logs
        
        try:
            # Ejecutamos la función RPC que definimos en SQL
            supabase.rpc("gdpr_forget_actor", {
                "p_tenant_id": tenant_id,
                "p_actor_id": req.actor_id
            }).execute()

            # AUDITORÍA DEL BORRADO (Obligatorio por ley para demostrar que lo hiciste)
            # Guardamos un registro de que "Alguien" fue borrado, sin decir quién era.
            logger.info(f"✅ GDPR Erasure completed for actor in tenant {tenant_id}")
            span.set_attribute("gdpr.status", "completed")
            
            return {
                "status": "completed",
                "message": "User data has been anonymized. Financial records remain intact.",
                "legal_note": "This action is irreversible and GDPR Article 17 compliant."
            }
        except Exception as e:
            span.set_attribute("gdpr.status", "error")
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"Compliance Error: {str(e)}")
