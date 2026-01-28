# app/routers/proxy.py
import json
import logging
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.limiter import limiter
from app.schema import DecisionContext
from app.services.cache import get_semantic_cache, set_semantic_cache  # [NEW] Cache Services
from app.services.carbon import carbon_governor
from app.services.event_bus import event_bus
from app.services.hud import HudMetrics, build_structured_event

# Servicios del Decision Graph
from app.services.identity import VerifiedIdentity, verify_identity_envelope
from app.services.llm_gateway import execute_with_resilience
from app.services.pii_guard import pii_guard
from app.services.pipeline import DecisionPipeline
from app.services.receipt_manager import receipt_manager

# [NEW] Role Fabric
from app.services.roles import role_fabric
from app.services.semantic_router import semantic_router
from app.services.trust_system import trust_system
from app.services.pricing_sync import get_model_pricing
from app.services.tokenizer import get_token_count

router = APIRouter()
logger = logging.getLogger("agentshield.proxy")


@router.post("/v1/chat/completions")
async def universal_proxy(
    request: Request,
    background_tasks: BackgroundTasks,
    identity: VerifiedIdentity = Depends(verify_identity_envelope),
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
    user_prompt = (
        messages[-1]["content"] if messages and isinstance(messages[-1].get("content"), str) else ""
    )

    # ==============================================================================
    # 1. DECISION PIPELINE (The Modular Core)
    # ==============================================================================
    ctx, messages, trust_policy, active_role, pii_result = await DecisionPipeline.process_request(
        request=request, identity=identity, messages=messages, requested_model=requested_model
    )

    # ==============================================================================
    # 2. STREAMING EXECUTION (Now with Hive Mind support)
    # ==============================================================================

    # [NEW] 6.1 Hive Memory Check
    hive_hit = False
    cached_response = None

    # Solo buscamos en caché si no es un regeneración forzada (opcional)
    # Y si el trust policy lo permite
    if trust_policy.get("allow_cache", True):
        cached_response = await get_semantic_cache(prompt=user_prompt, tenant_id=ctx.tenant_id)

    if cached_response:
        hive_hit = True
        ctx.log("CACHE", "🐝 Hive Hit! Serving from memory.")

        # Simulamos un generador compatible con el protocolo
        async def mock_upstream_gen():
            # Simulamos tokens para el efecto de escritura si se desea, o dump completo
            # Para UX "God Tier", entregamos rápido pero en chunks para no romper el frontend
            chunk_size = 10
            words = cached_response.split(" ")
            for i in range(0, len(words), chunk_size):
                chunk_text = " ".join(words[i : i + chunk_size]) + " "
                yield {"choices": [{"delta": {"content": chunk_text}}], "model": "hive-memory-v1"}
                # Pequeño sleep para que se sienta fluido, no instantáneo (opcional)
                # await asyncio.sleep(0.01)

        upstream_gen = mock_upstream_gen()
        # Ajustamos el modelo efectivo para reporting
        ctx.effective_model = "hive-memory"

    else:
        # [OLD] 6.2 Real execution
        try:
            # Calls the streaming version of gateway
            upstream_gen = await execute_with_resilience(
                tier=ctx.effective_model, messages=messages, user_id=identity.user_id, stream=True
            )
        except Exception as e:
            logger.error(f"Gateway Error: {e}")
            raise HTTPException(502, "AI Provider Gateway Error")

    # ==============================================================================
    # 7. WRAPPER (HUD Injection)
    # ==============================================================================

    # --- 2. PREPARACIÓN DE MÉTRICAS REALES ---
    # Obtenemos precios reales para el modelo solicitado y el efectivo
    req_pricing = await get_model_pricing(ctx.requested_model)
    eff_pricing = await get_model_pricing(ctx.effective_model)
    
    pricing_context = {
        "requested": req_pricing,
        "effective": eff_pricing,
        "model": ctx.effective_model,
        "requested_model": ctx.requested_model,
        "provider": "litellm", # O detectar de la cadena del modelo
        "tenant_id": ctx.tenant_id
    }

    user_context = {
        "trust_score": trust_policy["trust_score"],
        "pii_redactions": pii_result.get("findings_count", 0),
        "intent": ctx.intent,
        "role_name": role_name,
        "active_rules": active_rules,
        "hive_hit": hive_hit,
        "prompt_text": user_prompt,
    }
    
    # Conteo de tokens real
    input_tokens_real = get_token_count(user_prompt, ctx.effective_model)

    async def stream_with_hud_protocol(upstream, trace_id, start_ts, context, pricing, tokens_in):
        output_text = ""

        # A. Relay del Stream original
        async for chunk in upstream:
            content = None
            if hasattr(chunk, "choices") and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if hasattr(delta, "content") and delta.content:
                    content = delta.content
            elif isinstance(chunk, dict):
                content = chunk.get("choices", [{}])[0].get("delta", {}).get("content")

            if content:
                output_text += content
                chunk_dict = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
                yield f"data: {json.dumps(chunk_dict)}\n\n"
            else:
                chunk_dict = chunk.model_dump() if hasattr(chunk, "model_dump") else chunk
                yield f"data: {json.dumps(chunk_dict)}\n\n"

        # B. Cálculos al Finalizar Stream (Perfection Level)
        end_time = time.time()
        latency = int((end_time - start_ts) * 1000)
        output_tokens_final = get_token_count(output_text, pricing["model"])

        # Calculos Financieros Reales (Arbitraje Expuesto)
        p_eff = pricing["effective"]
        p_req = pricing["requested"]
        
        real_cost = (tokens_in * p_eff["price_in"]) + (output_tokens_final * p_eff["price_out"])
        requested_cost = (tokens_in * p_req["price_in"]) + (output_tokens_final * p_req["price_out"])
        
        # El ahorro es la diferencia entre lo que habrían pagado y lo que pagan hoy
        savings = max(0, requested_cost - real_cost)
        if context.get("hive_hit"):
             # Si es hit, el coste es casi 0 (solo infraestructura), el ahorro es total
             savings = requested_cost
             real_cost = 0.0001 

        # Calculos CO2
        co2 = carbon_governor.estimate_footprint(pricing["model"], tokens_in, output_tokens_final)
        co2_gross = carbon_governor.estimate_footprint(pricing["requested_model"], tokens_in, output_tokens_final)
        co2_avoided = max(0, co2_gross - co2)

        metrics = HudMetrics(
            request_id=trace_id,
            model_used=pricing["model"],
            provider=pricing["provider"],
            latency_ms=latency,
            tokens_total=tokens_in + output_tokens_final,
            cost_usd=real_cost,
            savings_usd=savings,
            co2_grams=co2,
            co2_saved_grams=co2_avoided,
            trust_score=context["trust_score"],
            pii_redactions=context["pii_redactions"],
            intent=context["intent"],
            role=context["role_name"],
            active_rules=context["active_rules"],
        )

        # D. Generamos la HUD Card (Elite Formatting)
        protection_status = "✅ **Protegido**" if metrics.trust_score > 70 else "🛡️ **Vigilancia**"
        hive_tag = " | 🐝 **Hive Mind**" if context.get("hive_hit") else ""
        
        hud_md = (
            f"\n\n---\n"
            f"**🛡️ AgentShield Status:** {protection_status} | **Role:** `{context['role_name']}`\n"
            f"**💰 Ahorro Real:** `${metrics.savings_usd:.4f}` | **⚡ Latencia:** `{metrics.latency_ms}ms`{hive_tag}\n"
            f"**🌱 Impacto:** `-{metrics.co2_saved_grams:.2f}g CO2e` | **PII Filter:** `{metrics.pii_redactions}`"
        )

        fake_chunk = {
            "id": "as-hud-" + trace_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": pricing["model"],
            "choices": [{"index": 0, "delta": {"content": hud_md}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(fake_chunk)}\n\n"
        yield build_structured_event(metrics)
        yield "data: [DONE]\n\n"

        # E. Persistencia Asíncrona vía BackgroundTasks (Production Best Practice)
        background_tasks.add_task(
            receipt_manager.create_and_sign_receipt,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            request_data={"model": ctx.effective_model, "trace_id": ctx.trace_id},
            response_data={"metrics": metrics.model_dump()},
            metadata=ctx.model_dump()
        )
        
        if not context.get("hive_hit") and output_tokens_final > 20:
            background_tasks.add_task(
                set_semantic_cache,
                prompt=context.get("prompt_text"),
                response=output_text,
                tenant_id=ctx.tenant_id
            )

    return StreamingResponse(
        stream_with_hud_protocol(
            upstream_gen, ctx.trace_id, start_time, user_context, pricing_context, input_tokens_real
        ),
        media_type="text/event-stream",
    )
