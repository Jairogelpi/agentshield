from fastapi import APIRouter, Request, Depends, BackgroundTasks, HTTPException
from app.services.identity import verify_identity_envelope, VerifiedIdentity
from app.services import billing
from app.services.limiter import check_hierarchical_budget, charge_hierarchical_wallets
from litellm import image_generation
import logging

router = APIRouter(tags=["Images & Creativity"])
logger = logging.getLogger("agentshield.images")

@router.post("/v1/images/generations")
async def proxy_images(
    request: Request,
    background_tasks: BackgroundTasks,
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    Proxy Generativo para DALL-E 3.
    Intercepta, Gobierna y Cobra la Creatividad.
    """
    try:
        body = await request.json()
    except:
        body = {}
        
    model = body.get("model", "dall-e-3")
    prompt = body.get("prompt", "")
    size = body.get("size", "1024x1024")
    quality = body.get("quality", "standard")
    
    # 1. GOBIERNO FINANCIERO (Presupuesto)
    # Calculamos coste dinámico usando el Estimador (consulta DB/Redis)
    from app.estimator import estimator
    
    # input_unit_count=1 (1 imagen)
    estimated_cost = await estimator.estimate_cost(
        model=model, 
        task_type="IMG_GENERATION", 
        input_unit_count=1,
        metadata={"quality": quality, "size": size}
    )
        
    # Verificar si el usuario tiene fondos
    can_spend, msg = await check_hierarchical_budget(identity, estimated_cost)
    if not can_spend:
        logger.warning(f"🎨 Image Gen Blocked for {identity.email}: {msg}")
        raise HTTPException(402, f"Insufficient Budget for Creativity: {msg}")

    logger.info(f"🎨 Generating Image ({model}) for {identity.email} - Cost: ${estimated_cost}")

    # 2. EJECUCIÓN (Llamada a OpenAI via LiteLLM)
    try:
        response = await image_generation(
            prompt=prompt,
            model=model,
            size=size,
            quality=quality,
            n=1 # Forzamos 1 por seguridad de costes por ahora
        )
    except Exception as e:
        logger.error(f"Image Gen Error: {e}")
        raise HTTPException(500, f"Upstream Generation Error: {str(e)}")
    
    # 3. COBRO REAL Y EVIDENCIA
    # Descontamos de los wallets en background
    background_tasks.add_task(charge_hierarchical_wallets, identity, estimated_cost)
    
    # Registramos la transacción
    # Nota: DALL-E no tiene 'tokens', usamos '1' como input unit.
    background_tasks.add_task(
        billing.record_transaction,
        tenant_id=identity.tenant_id,
        cost_center_id=identity.dept_id or "default",
        cost_real=estimated_cost,
        metadata={
            "interaction_type": "IMAGE_GENERATION",
            "model": model,
            "size": size,
            "quality": quality,
            "user_email": identity.email
        }
    )
    
    return response
