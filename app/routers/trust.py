from fastapi import APIRouter, Depends
from app.services.identity import verify_identity_envelope, VerifiedIdentity
from app.services.trust_system import trust_system

router = APIRouter(tags=["Trust Management"])

@router.post("/v1/trust/acknowledge-training")
async def acknowledge_training(
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    Válvula de Amnistía.
    Restaura el score a 70 (umbral mínimo para modelos Premium) si el usuario 
    reconoce formalmente las políticas de seguridad.
    """
    tenant_id = str(identity.tenant_id)
    user_id = identity.user_id
    
    # 1. Verificar score actual
    current_score = await trust_system.get_score(tenant_id, user_id)
    
    if current_score >= 70:
        return {
            "status": "healthy",
            "message": "Your trust score is already sufficient to access all models."
        }

    # 2. Restaurar a 70 (Amnistía)
    delta = 70 - current_score
    
    new_score = await trust_system.adjust_score(
        tenant_id=tenant_id,
        user_id=user_id,
        delta=delta,
        reason="User completed mandatory security training acknowledgment",
        event_type="TRAINING_COMPLETION",
        metadata={"action": "AMNESTY_RESET"}
    )
    
    return {
        "status": "restored", 
        "new_score": new_score,
        "message": "Trust level restored to 70. Access to premium models granted. Please follow security policies."
    }
