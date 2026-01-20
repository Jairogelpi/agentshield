# app/routers/proxy.py
import uuid
import time
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse

# Servicios del Decision Graph
from app.services.identity import verify_identity_envelope, VerifiedIdentity
from app.services.semantic_router import semantic_router
from app.services.trust_system import trust_system
from app.services.pii_guard import pii_guard
from app.services.carbon import carbon_governor
from app.limiter import limiter
from app.services.llm_gateway import execute_with_resilience
from app.services.receipt_manager import receipt_manager
from app.services.event_bus import event_bus
from app.schema import DecisionContext
# [NEW] Role Fabric
from app.services.roles import role_fabric
from app.services.hud import HudMetrics, build_structured_event

router = APIRouter()
logger = logging.getLogger("agentshield.proxy")

@router.post("/v1/chat/completions")
async def universal_proxy(
    request: Request,
    background_tasks: BackgroundTasks,
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    El Corazón del AgentShield OS - Ahora con Live HUD Streaming.
    """
    start_time = time.time()
    
    # 0. INIT REQUEST
    try:
        body = await request.json()
    except:
        raise HTTPException(400, "Invalid JSON")
        
    messages = body.get("messages", [])
    requested_model = body.get("model", "agentshield-fast")
    user_prompt = messages[-1]['content'] if messages and isinstance(messages[-1].get('content'), str) else ""

    # ==============================================================================
    # 0.5 ROLE FABRIC (Operational Identity)
    # ==============================================================================
    # Fetch semantic role based on Dept/Function
    # Assuming identity has 'metadata' or we infer function. defaulting to 'Employee'
    user_function = getattr(identity, 'function', 'Employee') 
    active_role = await role_fabric.get_role(dept=str(identity.dept_id or "General"), function=user_function)
    
    # Inject System Persona if not present or replace generic one?
    # For now, prepending if messages[0] is not system.
    if messages and messages[0]['role'] != 'system':
        messages.insert(0, {"role": "system", "content": active_role.get("system_persona")})

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

    # 2. INTENT CLASSIFIER (Semantic Gate)
    ctx.intent = await semantic_router.classify_intent(ctx.tenant_id, user_prompt)
    ctx.log("INTENT", f"Classified as {ctx.intent}")
    
    # 3. RISK ENGINE (Trust Gate)
    trust_policy = await trust_system.enforce_policy(ctx.tenant_id, ctx.user_id, ctx.requested_model)
    if trust_policy["requires_approval"]:
        raise HTTPException(403, detail=f"⛔ Trust Lock: {trust_policy['blocking_reason']}")
    if trust_policy["effective_model"] != ctx.requested_model:
        ctx.effective_model = trust_policy["effective_model"]
        ctx.risk_mode = trust_policy["mode"]

    # 4. COMPLIANCE GATE (PII Check) -- Using Role Policy?
    # Could overwrite pii_guard mode with active_role['pii_policy']
    pii_result = await pii_guard.scan(messages)
    if pii_result.get("blocked"):
        raise HTTPException(400, "🛡️ AgentShield Security: Envío bloqueado por datos altamente sensibles.")
    if pii_result.get("changed"):
        messages = pii_result["cleaned_messages"]
        ctx.pii_redacted = True

    # 5. ARBITRAGE GATE (Financial Engine)
    if "agentshield-smart" in ctx.requested_model:
        ctx.effective_model = "gpt-4o" 
    elif "agentshield-fast" in ctx.requested_model:
        from app.services.arbitrage import arbitrage_engine
        analysis = await arbitrage_engine.analyze_complexity(messages)
        winner_id, reason, savings = await arbitrage_engine.find_best_bidder("gpt-4o-mini", analysis)
        if savings > 0 and winner_id:
            ctx.effective_model = winner_id

    # 5.5 CARBON GATE
    if ctx.effective_model == ctx.requested_model:
        ctx = await carbon_governor.check_budget_and_route(ctx)

    # 5.6 BUDGET GATE
    can_spend, limit_msg = await limiter.check_velocity_and_budget(identity)
    if not can_spend:
        raise HTTPException(429, detail=f"📉 AgentShield: {limit_msg}")

    # ==============================================================================
    # 6. STREAMING EXECUTION
    # ==============================================================================
    try:
        # Calls the streaming version of gateway
        upstream_gen = await execute_with_resilience(
            tier=ctx.effective_model,
            messages=messages,
            user_id=identity.user_id,
            stream=True
        )
    except Exception as e:
        logger.error(f"Gateway Error: {e}")
        raise HTTPException(502, "AI Provider Gateway Error")

    # ==============================================================================
    # 7. WRAPPER (HUD Injection)
    # ==============================================================================

    # Metadata para el calculo final
    model_pricing = {"model": ctx.effective_model, "provider": "openai", "price_in": 0.01, "price_out": 0.03}
    role_name = f"{active_role.get('department')} > {active_role.get('function')}"
    active_rules = active_role.get('metadata', {}).get('active_rules', [])
    
    user_context = {
        "trust_score": trust_policy['trust_score'], 
        "pii_redactions": pii_result.get("findings_count", 0),
        "intent": ctx.intent,
        "role_name": role_name,
        "active_rules": active_rules # Pass for HUD
    }
    input_tokens_est = int(len(user_prompt)/4) 

    async def stream_with_hud_protocol(upstream, request_id, start_ts, context, fees, tokens_in):
        output_text = ""
        
        # A. Relay del Stream original
        async for chunk in upstream:
            # Litellm/OpenAI chunk obj
            content = None
            if hasattr(chunk, "choices") and len(chunk.choices) > 0:
                 delta = chunk.choices[0].delta
                 if hasattr(delta, "content") and delta.content:
                     content = delta.content
            elif isinstance(chunk, dict):
                 content = chunk['choices'][0]['delta'].get('content')

            if content:
                output_text += content
                chunk_dict = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
                yield f"data: {json.dumps(chunk_dict)}\n\n"
            else:
                chunk_dict = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
                yield f"data: {json.dumps(chunk_dict)}\n\n"

        # B. Cálculos al Finalizar Stream
        end_time = time.time()
        latency = int((end_time - start_ts) * 1000)
        output_tokens_final = max(1, int(len(output_text) / 4))
        
        # Calculos Financieros (Simulados)
        cost_input = (tokens_in / 1000) * fees.get('price_in', 0)
        cost_output = (output_tokens_final / 1000) * fees.get('price_out', 0)
        total_cost = cost_input + cost_output
        savings = total_cost * 0.25 
        
        # Calculos CO2
        co2 = carbon_governor.estimate_footprint(ctx.effective_model, tokens_in, output_tokens_final)
        co2_gross = carbon_governor.estimate_footprint(ctx.requested_model, tokens_in, output_tokens_final)
        co2_avoided = max(0, co2_gross - co2)

        # C. Construir Metrics Object
        metrics = HudMetrics(
            request_id=request_id,
            model_used=fees['model'],
            provider=fees['provider'],
            latency_ms=latency,
            tokens_total=tokens_in + output_tokens_final,
            cost_usd=total_cost,
            savings_usd=savings,
            co2_grams=co2,
            co2_saved_grams=co2_avoided,
            trust_score=context['trust_score'],
            pii_redactions=context['pii_redactions'],
            intent=context['intent'],
            role=context['role_name'],
            active_rules=context['active_rules'] # [NEW]
        )

        # D. Generamos la HUD Card (Canal Visual)
        # [MODIFIED] User requested format
        hud_md = (
            f"\n\n---\n"
            f"**🛡️ AgentShield HUD** | **Role:** `{context['role_name']}` | **Trust:** `{metrics.trust_score}/100`  \n"
            f"**Savings:** `${metrics.savings_usd:.4f}` | **CO2 Saved:** `{metrics.co2_saved_grams:.2f}g`"
        )
        
        # Chunk artificial compatible con OpenAI
        fake_chunk = {
            "id": "as-hud-" + request_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": fees['model'],
            "choices": [{
                "index": 0,
                "delta": {"content": hud_md},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(fake_chunk)}\n\n"
        
        # E. Metadatos Estructurados (Canal Primario para Frontend)
        yield build_structured_event(metrics)
        yield "data: [DONE]\n\n"

        # F. Persistencia Asíncrona (Receipt & Logs)
        try:
             await receipt_manager.create_and_sign_receipt(
                 tenant_id=ctx.tenant_id,
                 user_id=ctx.user_id,
                 request_data={"model": ctx.effective_model, "trace_id": ctx.trace_id},
                 response_data={"metrics": str(metrics)}, 
                 metadata=ctx.model_dump()
             )
        except Exception as e:
            logger.error(f"Post-stream persistence failed: {e}")

    return StreamingResponse(
        stream_with_hud_protocol(
            upstream_gen, 
            ctx.trace_id, 
            start_time, 
            user_context, 
            model_pricing, 
            input_tokens_est
        ),
        media_type="text/event-stream"
    )
