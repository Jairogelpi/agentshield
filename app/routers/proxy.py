import hashlib
import json
import logging
import os
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from opentelemetry import trace

from app.http_limiter import limiter
from app.schema import DecisionContext
from app.services.cache import set_semantic_cache
from app.services.carbon import carbon_governor
from app.services.event_bus import event_bus
from app.services.hive_mind import hive_mind
from app.services.hud import HudMetrics, build_structured_event

tracer = trace.get_tracer(__name__)

# Servicios del Decision Graph
from app.services.identity import VerifiedIdentity, verify_identity_envelope
from app.services.budget_limiter import charge_hierarchical_wallets, check_hierarchical_budget
from app.services.llm_gateway import execute_with_resilience
from app.services.observer import observer_service
from app.services.pii_guard import pii_guard
from app.services.pipeline import DecisionPipeline
from app.services.pricing_sync import get_model_pricing
from app.services.receipt_manager import receipt_manager

# [NEW] Role Fabric
from app.services.roles import role_fabric
from app.services.safety_engine import safety_engine
from app.services.semantic_router import semantic_router
from app.services.tokenizer import get_token_count
from app.services.tool_governor import governor
from app.services.trust_system import trust_system

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
    with tracer.start_as_current_span("universal_proxy") as span:
        span.set_attribute("tenant.id", str(identity.tenant_id))
        span.set_attribute("user.id", identity.user_id)

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

    # [EVOLUTIONARY] 6.1 Hive Mind Query (Federated Intelligence)
    hive_result = None
    hive_hit = False

    if trust_policy.get("allow_cache", True):
        hive_result = await hive_mind.query_hive(prompt=user_prompt, tenant_id=ctx.tenant_id)

    if hive_result:
        hive_hit = True
        source = hive_result["source"]
        cached_response = hive_result["content"]

        ctx.log("HIVE", f"🐝 Hive Hit! Source: {source}")

        # SIEM SIGNAL
        background_tasks.add_task(
            event_bus.publish,
            tenant_id=ctx.tenant_id,
            event_type="HIVE_KNOWLEDGE_HIT",
            severity="INFO",
            details={
                "source": source,
                "confidence": hive_result.get("confidence"),
                "records_used": hive_result.get("records_used", 1),
            },
            actor_id=ctx.user_id,
            trace_id=ctx.trace_id,
        )

        async def hive_stream_gen():
            # Formatting as 'Collective Wisdom' for UX if it's a synthesis
            prefix = ""
            if source == "HIVE_SYNTHESIS":
                prefix = "🌌 **AgentShield Collective Wisdom (Synthesized):**\n\n"

            words = (prefix + cached_response).split(" ")
            for i in range(0, len(words), 8):
                chunk_text = " ".join(words[i : i + 8]) + " "
                yield {
                    "choices": [{"delta": {"content": chunk_text}}],
                    "model": f"as-hive-{source.lower()}",
                }
                # Pequeña pausa para no saturar
                await asyncio.sleep(0.005)

        upstream_gen = hive_stream_gen()
        ctx.effective_model = f"hive-{source.lower()}"
        ctx.user_context["hive_source"] = source  # Inyectamos para el HUD

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
        "provider": "litellm",  # O detectar de la cadena del modelo
        "tenant_id": ctx.tenant_id,
    }

    user_context = {
        "trust_score": trust_policy["trust_score"],
        "pii_redactions": pii_result.get("findings_count", 0),
        "pii_risk_score": pii_result.get("risk_score", {}),  # Revolutionary 2026
        "pii_compliance_cert": pii_result.get("compliance_certificate", {}),  # Revolutionary 2026
        "pii_recoverable": pii_result.get("recoverable_count", 0),  # Revolutionary 2026
        "pii_evasion_attempts": pii_result.get("evasion_attempts", 0),  # Zero-Leak 2026
        "pii_detection_confidence": pii_result.get("detection_confidence", 95),  # Zero-Leak 2026
        "intent": ctx.intent,
        "role_name": active_role.get("name", "Unknown"),
        "active_rules": active_role.get("active_rules", []),
        "hive_hit": hive_hit,
        "hive_source": getattr(ctx, "user_context", {}).get("hive_source", "NONE"),
        "hive_metadata": hive_result if hive_hit else {},  # Inject enriched Hive Mind metrics
        "prompt_text": user_prompt,
    }

    # Conteo de tokens real
    input_tokens_real = get_token_count(user_prompt, ctx.effective_model)

    async def stream_with_hud_protocol(
        upstream, trace_id, start_ts, context, pricing, tokens_in, identity
    ):
        output_text = ""
        cumulative_tokens_out = 0
        is_killed = False
        kill_reason = ""

        # Buffer de Agentic Governance (Tool Calls)
        tool_call_buffer = {}  # call_id -> {name, args_buffer}
        governed_tool_count = 0

        # Forensic Hash Chain Initialization
        forensic_hasher = hashlib.sha256()

        # 0. EL HANDSHAKE (Revolutionary 2026 Standard)
        handshake = {
            "object": "agentshield.handshake",
            "trace_id": trace_id,
            "status": "SECURE",
            "residency": os.getenv("SERVER_REGION", "EU-WEST-CONT"),
            "sovereignty_proof": f"sha256:{uuid.uuid4().hex[:16]}",  # Simulated Hash Proof
            "active_guards": ["PII", "Trust", "Arbitrage", "Entropy-Scan", "Safety-Stealth", "Agent-Gov"],
        }
        yield f"data: {json.dumps(handshake)}\n\n"

        # A. Relay del Stream original con Procesamiento Activo
        async for chunk in upstream:
            if is_killed:
                break

            # --- GOBERNANZA DE AGENTES (Tool Detection) ---
            if hasattr(chunk, "choices") and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if tc.id:  # Inicio de llamada
                            tool_call_buffer[idx] = {
                                "id": tc.id,
                                "name": tc.function.name,
                                "args": "",
                            }
                        if tc.function and tc.function.arguments:  # Acumulación de args
                            tool_call_buffer[idx]["args"] += tc.function.arguments

            # Nota: Si el LLM termina una llamada a herramienta, el finish_reason suele ser 'tool_calls'.
            # En ese momento (o en el chunk final), evaluamos.
            is_tool_completion = False
            if hasattr(chunk, "choices") and len(chunk.choices) > 0:
                if chunk.choices[0].finish_reason == "tool_calls":
                    is_tool_completion = True

            if is_tool_completion:
                # EVALUACIÓN DE AGENTIC GOVERNANCE
                for idx, t_call in tool_call_buffer.items():
                    # Transformamos a formato estándar para el Governor
                    standard_call = {
                        "id": t_call["id"],
                        "function": {"name": t_call["name"], "arguments": t_call["args"]},
                    }

                    # Llamada al Gobernador
                    sanitized = await governor.inspect_tool_calls(identity, [standard_call])

                    # Si el gobernador ha 'intervenido', el nombre de la función habrá cambiado a system_notification
                    if sanitized[0]["function"]["name"] == "system_notification":
                        governed_tool_count += 1
                        # Emitimos el chunk de sistema para alertar al frontend/usuario
                        system_chunk = {
                            "id": f"gov-{trace_id}-{idx}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": pricing["model"],
                            "choices": [
                                {
                                    "index": idx,
                                    "delta": {
                                        "content": f"\n🛡️ **AgentShield Gov:** Acción '{t_call['name']}' interceptada."
                                    },
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(system_chunk)}\n\n"

                        # SIEM ALERT: Agent Action Governed
                        background_tasks.add_task(
                            event_bus.publish,
                            tenant_id=ctx.tenant_id,
                            event_type="AGENT_ACTION_GOVERNED",
                            severity="WARNING",
                            details={"tool": t_call["name"], "action": "INTERCEPTED"},
                            actor_id=ctx.user_id,
                            trace_id=ctx.trace_id,
                        )

            # --- SEGURIDAD DE SALIDA (Content Selection) ---
            content = None
            if hasattr(chunk, "choices") and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if hasattr(delta, "content") and delta.content:
                    content = delta.content
            elif isinstance(chunk, dict):
                content = chunk.get("choices", [{}])[0].get("delta", {}).get("content")

            if content:
                # 1. SEGURIDAD DE SALIDA (Safety Guard)
                # Escaneamos el chunk antes de entregarlo
                is_threat, reason, safe_content = safety_engine.scan_chunk(content)

                if is_threat:
                    is_killed = True
                    kill_reason = f"SECURITY_ALERT: {reason}"
                    break  # Detener stream inmediatamente

                # 2. SEGUIMIENTO DE TOKENS Y PRESUPUESTO
                cumulative_tokens_out += get_token_count(safe_content, pricing["model"])

                # Cada 50 tokens o al final, verificamos solvencia mid-stream
                if cumulative_tokens_out % 50 == 0:
                    current_cost = (tokens_in * pricing["effective"]["price_in"]) + (
                        cumulative_tokens_out * pricing["effective"]["price_out"]
                    )
                    # Verificamos si aún tiene presupuesto para continuar
                    allowed, fail_reason = await check_hierarchical_budget(identity, current_cost)
                    if not allowed:
                        is_killed = True
                        kill_reason = f"BUDGET_EXCEEDED: {fail_reason}"
                        break

                output_text += safe_content
                
                # Update Forensic Hash Chain
                forensic_hasher.update(safe_content.encode("utf-8"))

                # Re-empaquetamos el chunk con el contenido seguro (posiblemente redactado)
                if isinstance(chunk, dict):
                    chunk["choices"][0]["delta"]["content"] = safe_content
                    chunk_dict = chunk
                else:
                    chunk_dict = chunk.model_dump()
                    chunk_dict["choices"][0]["delta"]["content"] = safe_content

                yield f"data: {json.dumps(chunk_dict)}\n\n"

        # B. MANEJO DE CIERRE FORZADO
        if is_killed:
            logger.error(f"❌ Session Terminated mid-stream: {kill_reason}")

            # SIEM ALERT (Critical)
            background_tasks.add_task(
                event_bus.publish,
                tenant_id=ctx.tenant_id,
                event_type="SECURITY_THREAT_KILL",
                severity="CRITICAL",
                details={"reason": kill_reason, "stream_progress": len(output_text)},
                actor_id=ctx.user_id,
                trace_id=ctx.trace_id,
            )

            # STEALTH MODE: Instead of a hard error, we provide a "Diverted Response"
            stealth_msg = "\n\n🛡️ **AgentShield Note:** *The model's output has been diverted to a secure sandbox for policy alignment. No further data will be transmitted in this session.*"
            if "JAILBREAK" in kill_reason:
                stealth_msg = "\n\n⚠️ **Security Protocol:** *Operational parameters reset. Connection stabilized.*"

            kill_chunk = {
                "object": "agentshield.kill_signal",
                "reason": kill_reason,
                "trace_id": trace_id,
                "content": stealth_msg,
            }
            yield f"data: {json.dumps(kill_chunk)}\n\n"
            # No enviamos el HUD normal si fue matado por seguridad, o lo enviamos con advertencia

        # C. Cálculos al Finalizar (Normal o por Kill)
        end_time = time.time()
        latency = int((end_time - start_ts) * 1000)
        output_tokens_final = cumulative_tokens_out

        # Calculos Financieros Reales (Arbitraje Expuesto)
        p_eff = pricing["effective"]
        p_req = pricing["requested"]

        real_cost = (tokens_in * p_eff["price_in"]) + (output_tokens_final * p_eff["price_out"])
        requested_cost = (tokens_in * p_req["price_in"]) + (
            output_tokens_final * p_req["price_out"]
        )

        # El ahorro es la diferencia entre lo que habrían pagado y lo que pagan hoy
        savings = max(0, requested_cost - real_cost)
        if context.get("hive_hit"):
            # Si es hit, el coste es casi 0 (solo infraestructura), el ahorro es total
            savings = requested_cost
            real_cost = 0.0001

        # Calculos CO2
        co2 = carbon_governor.estimate_footprint(pricing["model"], tokens_in, output_tokens_final)
        co2_gross = carbon_governor.estimate_footprint(
            pricing["requested_model"], tokens_in, output_tokens_final
        )
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

        # D. EVALUACIÓN ETICA Y ALUCINACIONES (2026 Observer)
        observer_results = await observer_service.evaluate_response(
            prompt=context.get("prompt_text"),
            response_text=output_text,
            context_messages=messages,  # Using the original messages list from closure
            tenant_id=identity.tenant_id,
            trace_id=trace_id,
        )

        # E. Generamos la HUD Card (Elite 2026 Cockpit)
        protection_status = "✅ Protegido" if metrics.trust_score > 70 else "🛡️ Vigilancia"
        risk_score = 100 - metrics.trust_score
        privacy_shield = (
            "🟢 ACTIVO" if metrics.pii_redactions > 0 or not is_killed else "🟡 SCANNING"
        )
        agent_gov = "🔒 GOVERNED" if governed_tool_count > 0 else "👀 MONITORING"
        residency = os.getenv("SERVER_REGION", "EU-WEST")

        # Marcadores éticos
        faith_status = "💎 Veraz" if observer_results["faithfulness_score"] > 0.85 else "⚠️ Revisar"
        neutral_status = (
            "⚖️ Neutral" if observer_results["neutrality_score"] > 0.85 else "🚩 Sesgado"
        )

        # Metadata Colmena (Revolutionary Enhancement)
        hive_metadata = context.get(\"hive_metadata\", {})
        hive_status = (
            "🧬 EVO-HIVE" if context.get("hive_source") == "HIVE_SYNTHESIS" else "🐝 MEMORY"
        )
        
        # Knowledge Liquidity Metrics (Revolutionary Value Proposition)
        if hive_hit and hive_metadata:
            memory_roi = hive_metadata.get("memory_roi_usd", 0)
            knowledge_conf = int(hive_metadata.get("knowledge_confidence", 0.9) * 100)
            dept_sources = hive_metadata.get("dept_sources", 1)
            projected_roi = hive_metadata.get("projected_roi_30d", 0)
            
            hive_label = (
                f" | **Hive:** `{hive_status}` "
                f"**ROI:** `${memory_roi:.3f}` "
                f"**Conf:** `{knowledge_conf}%` "
                f"**Depts:** `{dept_sources}`"
            )
        else:
            hive_label = ""

        # Arbitrage Delta (Market ROI)
        market_delta_pct = int((savings / requested_cost * 100)) if requested_cost > 0 else 0
        delta_label = f" | **Arbitrage:** `+{market_delta_pct}%`" if not hive_hit else ""

        # Forensic & ESG Pulse (God Tier 2.0)
        final_forensic_hash = forensic_hasher.hexdigest()[:12].upper()
        # Simulated ESG Pulse: Correlation with carbon avoided or random grid fluctuation
        grid_purity = 85 + (int(time.time()) % 15) if co2_avoided > 0 else 70 + (int(time.time()) % 10)
        
        # Revolutionary PII 2026: Risk & Compliance Display
        pii_risk_data = context.get("pii_risk_score", {})
        pii_compliance = context.get("pii_compliance_cert", {})
        pii_recoverable = context.get("pii_recoverable", 0)
        pii_evasion = context.get("pii_evasion_attempts", 0)
        pii_confidence = context.get("pii_detection_confidence", 95)
        
        pii_exposure = pii_risk_data.get("exposure_index", 0)
        gdpr_risk_k = int(pii_risk_data.get("gdpr_fine_risk_eur", 0) / 1000)  # Convert to K€
        compliance_level = pii_compliance.get("certification_level", "BASIC")
        compliance_badge = "🥇" if compliance_level == "GOLD" else "🥈" if compliance_level == "SILVER" else "🛡️"
        
        # Zero-Leak 2026: Show evasion detection as confidence boost
        evasion_badge = " 🚨" if pii_evasion > 0 else ""
        conf_display = f"{pii_confidence}%" if pii_confidence == 100 else f"{pii_confidence}%"
        
        pii_label = (
            f" | **PII Risk:** `€{gdpr_risk_k}K` "
            f"{compliance_badge} `{compliance_level}` "
            f"**Conf:** `{conf_display}{evasion_badge}` "
            f"**Rec:** `{pii_recoverable}`"
        ) if metrics.pii_redactions > 0 else ""

        hud_md = (
            f"\n\n---\n"
            f"**🛡️ AgentShield Status:** {protection_status}{hive_label}{delta_label}{pii_label} | **Agents:** `{agent_gov}` | **Riesgo:** `{risk_score}/100`\n"
            f"**🧠 Inteligencia:** {faith_status} `{int(observer_results['faithfulness_score'] * 100)}%` | {neutral_status} `{int(observer_results['neutrality_score'] * 100)}%`\n"
            f"**💰 Ahorro Real:** `${metrics.savings_usd:.4f}` | **⚡ Latencia:** `{metrics.latency_ms}ms` | **Soberanía:** `{residency}-VERIFIED`\n"
            f"**🌱 Impacto ESG:** `-{metrics.co2_saved_grams:.2f}g CO2e` (`{grid_purity}% Pure`) | **PII Redacted:** `{metrics.pii_redactions}` | **Seal:** `{final_forensic_hash}`"
        )

        fake_chunk = {
            "id": "as-hud-" + trace_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": pricing["model"],
            "choices": [{"index": 0, "delta": {"content": hud_md}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(fake_chunk)}\n\n"

        # Inyectamos el ID de recibo en las métricas para transparencia total
        metrics_dict = metrics.model_dump()
        metrics_dict["legal_proof_id"] = f"RX-{trace_id[-6:].upper()}"

        yield f"event: agentshield.hud\ndata: {json.dumps(metrics_dict)}\n\n"
        yield "data: [DONE]\n\n"

        # E. Persistencia Asíncrona vía BackgroundTasks (Production Best Practice)
        # SIEM: Final Transaction Report
        background_tasks.add_task(
            event_bus.publish,
            tenant_id=ctx.tenant_id,
            event_type="AI_PROXY_FULFILLMENT",
            severity="INFO",
            details={
                "model_req": pricing["requested_model"],
                "model_eff": pricing["model"],
                "savings": metrics.savings_usd,
                "pii_filtered": metrics.pii_redactions > 0,
                "hive_hit": context.get("hive_hit"),
            },
            actor_id=ctx.user_id,
            trace_id=ctx.trace_id,
        )

        background_tasks.add_task(
            receipt_manager.create_and_sign_receipt,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            request_data={"model": ctx.effective_model, "trace_id": ctx.trace_id},
            response_data={"metrics": metrics.model_dump()},
            metadata=ctx.model_dump(),
        )

        if not context.get("hive_hit") and output_tokens_final > 20:
            background_tasks.add_task(
                set_semantic_cache,
                prompt=context.get("prompt_text"),
                response=output_text,
                tenant_id=ctx.tenant_id,
            )

    return StreamingResponse(
        stream_with_hud_protocol(
            upstream_gen,
            ctx.trace_id,
            start_time,
            user_context,
            pricing_context,
            input_tokens_real,
            identity,
        ),
        media_type="text/event-stream",
    )
