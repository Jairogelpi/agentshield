# app/routers/proxy.py
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse

# Servicios del Decision Graph
from app.services.identity import verify_identity_envelope, VerifiedIdentity
from app.services.semantic_router import semantic_router
from app.services.trust_system import trust_system
from app.services.pii_guard import pii_guard
from app.services.carbon import carbon_governor
from app.services.llm_gateway import execute_with_resilience
from app.services.receipt_manager import receipt_manager
from app.schema import DecisionContext

router = APIRouter()
logger = logging.getLogger("agentshield.proxy")

@router.post("/v1/chat/completions")
async def universal_proxy(
    request: Request,
    background_tasks: BackgroundTasks,
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    El Corazón del AgentShield OS.
    Flujo: Identity -> Trust -> Semantic -> PII -> Budget -> Execution -> Audit
    """
    
    # 0. INIT REQUEST
    try:
        body = await request.json()
    except:
        raise HTTPException(400, "Invalid JSON")
        
    messages = body.get("messages", [])
    requested_model = body.get("model", "agentshield-fast")
    user_prompt = messages[-1]['content'] if messages and isinstance(messages[-1].get('content'), str) else ""

    # ==============================================================================
    # 1. CONTEXT BUILDER
    # ==============================================================================
    ctx = DecisionContext(
        trace_id=f"trc_{uuid.uuid4().hex[:12]}",
        tenant_id=str(identity.tenant_id),
        user_id=identity.user_id,
        dept_id=str(identity.dept_id or ""),
        email=identity.email,
        requested_model=requested_model,
        effective_model=requested_model
    )

    # ==============================================================================
    # 2. INTENT CLASSIFIER (Semantic Gate)
    # ==============================================================================
    ctx.intent = await semantic_router.classify_intent(ctx.tenant_id, user_prompt)
    ctx.log("INTENT", f"Classified as {ctx.intent}")
    
    # ==============================================================================
    # 3. RISK ENGINE (Trust Gate)
    # ==============================================================================
    trust_policy = await trust_system.enforce_policy(ctx.tenant_id, ctx.user_id, ctx.requested_model)
    
    if trust_policy["requires_approval"]:
        logger.warning(f"🛡️ TRUST LOCK: User {identity.email} score {trust_policy['trust_score']}")
        raise HTTPException(403, detail=f"⛔ Trust Lock: {trust_policy['blocking_reason']}")
        
    if trust_policy["effective_model"] != ctx.requested_model:
        ctx.effective_model = trust_policy["effective_model"]
        ctx.risk_mode = trust_policy["mode"]
        ctx.log("RISK", f"Downgraded to {ctx.effective_model} due to Trust Score")

    # ==============================================================================
    # 4. COMPLIANCE GATE (PII Check)
    # ==============================================================================
    pii_result = await pii_guard.scan(messages)
    if pii_result.get("blocked"):
        background_tasks.add_task(
            trust_system.adjust_score,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            delta=-20,
            reason="Security Block: High Sensitivity PII detected",
            event_type="PII_BLOCK"
        )
        raise HTTPException(400, "🛡️ AgentShield Security: Envío bloqueado por datos altamente sensibles.")
    
    if pii_result.get("changed"):
        messages = pii_result["cleaned_messages"]
        ctx.pii_redacted = True
        ctx.log("COMPLIANCE", "PII Redacted")
        background_tasks.add_task(
            trust_system.adjust_score,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            delta=-5,
            reason="Security Warning: PII redacted automatically",
            event_type="PII_REDACT"
        )

    # ==============================================================================
    # 5. CARBON GATE (Green Routing)
    # ==============================================================================
    # Solo aplicamos si el motor de riesgo no ha degradado ya el modelo
    if ctx.effective_model == ctx.requested_model:
        ctx = await carbon_governor.check_budget_and_route(ctx)

    # ==============================================================================
    # 6. EXECUTION ROUTER
    # ==============================================================================
    try:
        response = await execute_with_resilience(
            model=ctx.effective_model,
            messages=messages,
            user_id=identity.user_id
        )
    except Exception as e:
        logger.error(f"Gateway Error: {e}")
        raise HTTPException(502, "AI Provider Gateway Error")

    # ==============================================================================
    # 7. RECEIPT & SETTLEMENT (Async)
    # ==============================================================================
    # Calculamos CO2 real post-ejecución
    usage = getattr(response, 'usage', None)
    prompt_tokens = usage.prompt_tokens if usage else 1000
    completion_tokens = usage.completion_tokens if usage else 0
    
    co2_actual = carbon_governor.estimate_footprint(ctx.effective_model, prompt_tokens, completion_tokens)
    
    background_tasks.add_task(
        carbon_governor.log_emission,
        ctx.tenant_id, ctx.dept_id, ctx.user_id, 
        ctx.trace_id, ctx.effective_model, co2_actual
    )
    
    background_tasks.add_task(
        receipt_manager.create_and_sign_receipt,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        request_data={"model": ctx.effective_model, "trace_id": ctx.trace_id},
        response_data=response,
        metadata=ctx.model_dump()
    )

    # 8. RESPONSE
    content = json.loads(response.json()) if hasattr(response, "json") else response
    final_response = JSONResponse(content=content)
    
    final_response.headers["X-AgentShield-Trace-ID"] = ctx.trace_id
    final_response.headers["X-AgentShield-Trust-Score"] = str(trust_policy["trust_score"])
    
    if ctx.green_routing_active:
        final_response.headers["X-AgentShield-Green"] = "Routed to Eco Model 🌱"
        
    if ctx.effective_model != ctx.requested_model and not ctx.green_routing_active:
        final_response.headers["X-AgentShield-Notice"] = "Model Downgraded due to Risk Policy"
    
    return final_response
