import os
import json
import asyncio
from fastapi import APIRouter, Request, Header, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from litellm import acompletion 
from app.routers.authorize import get_tenant_from_header
from app.services.billing import record_transaction
from app.estimator import estimator
from app.db import redis_client
from app.limiter import limiter
import re
from app.logic import create_aut_token, verify_residency
from app.logic import create_aut_token, verify_residency
from app.services.cache import get_semantic_cache_full_data, set_semantic_cache
from app.services.reranker import verify_cache_logic
from app.services.vault import get_secret
from app.services.pii_guard import advanced_redact_pii
from app.services.carbon import calculate_footprint
from opentelemetry.trace import Status, StatusCode

# Helper para trazas seguras (PII Firewall para OTEL)
def record_safe_exception(span, e: Exception):
    """
    Registra una excepción en el Trace pero censura el mensaje.
    """
    # Creamos una 'copia' limpia del mensaje de error
    safe_msg = advanced_redact_pii(str(e))
    
    # Registramos un evento de error manual en lugar de la excepción cruda
    span.add_event("exception", {
        "exception.type": type(e).__name__,
        "exception.message": safe_msg, # Mensaje limpio
        "exception.stacktrace": "Stacktrace withheld for PII safety" # Opcional: ocultar stacktrace si contiene datos
    })
    
    span.set_status(Status(StatusCode.ERROR, safe_msg))
from opentelemetry import trace
import logging
import time

logger = logging.getLogger("agentshield.security")
tracer = trace.get_tracer(__name__)
import os

# Leemos la región del servidor desde las variables de entorno de Render
CURRENT_REGION = os.getenv("SERVER_REGION", "eu")

# --- SEMANTIC FIREWALL HELPERS ---
# --- SEMANTIC FIREWALL HELPERS ---
async def detect_risk_with_llama_guard(messages: list) -> bool:
    """
    Llama-Guard 3 Firewall con política Fail-Closed.
    """
    with tracer.start_as_current_span("security_guard_check") as span:
        try:
            # Formateamos la consulta para Llama-Guard
            response = await acompletion(
                model="groq/llama-guard-3-8b", 
                messages=messages,
                temperature=0.0 
            )
            
            verdict = response.choices[0].message.content.lower()
            span.set_attribute("security.verdict", verdict)

            if "unsafe" in verdict:
                logger.error(f"🔥 Security Threat Blocked: {verdict}")
                return True # UNSAFE
                
            return False # SAFE
            
        except Exception as e:
            # 2026 Standard: Fail-Closed. 
            # Si el servicio de seguridad no responde, NO se procesa la petición.
            # PII FIREWALL: Censuramos la excepción antes de enviarla a Grafana
            record_safe_exception(span, e)
            logger.critical(f"🚨 Safety Layer Failure (Fail-Closed triggered): {e}")
            return True # Asumimos riesgo si no podemos verificar

async def final_security_audit(guard_task: asyncio.Task, trace_id: str):
    """Auditoría en segundo plano si Llama-Guard tardó demasiado"""
    try:
        is_unsafe = await guard_task
        if is_unsafe:
            # CRITICAL: Esto debe despertar al equipo de seguridad
            logger.critical(f"🚨 Security Alert (Post-Response): Trace {trace_id} contained unsafe content.")
            # Aquí podrías marcar el trace como "flagged" en DB
    except Exception as e:
        logger.error(f"Background Guard Error: {e}")




router = APIRouter(tags=["Universal Proxy"])

# Este proxy acepta peticiones en formato estándar y las enruta a CUALQUIER proveedor
# Soportados: OpenAI, Anthropic, Google Vertex, AWS Bedrock, Ollama, HuggingFace, etc.

@router.post("/v1/chat/completions")
@limiter.limit("600/minute")
async def universal_proxy(
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: str = Header(...)
):
    with tracer.start_as_current_span("universal_proxy_flow") as span:
        # Obtener el contexto de traza actual generado por el middleware (propagado auto por otel, pero forzamos id)
        trace_id = format(span.get_span_context().trace_id, '032x')
        start_time = time.time()

        # 1. AUTENTICACIÓN AGENTSHIELD (Tu seguridad)
        try:
            as_key = authorization.replace("Bearer ", "").strip()
            tenant_id = await get_tenant_from_header(x_api_key=as_key)
            
            # 1.1 BLOQUEO LEGAL (Hard Enforcement)
            await verify_residency(tenant_id)

            # 1.2 Obtener Cost Center por defecto (Para facturación)
            cost_center_id = await get_proxy_cost_center(tenant_id)
        except Exception as e:
            if isinstance(e, HTTPException): raise e
            raise HTTPException(status_code=401, detail="Invalid AgentShield API Key")

        # 2. LEER PETICIÓN (Agnóstica)
        body = await request.json()
        model = body.get("model") 
        messages_raw = body.get("messages", []) # RAW
        stream = body.get("stream", False)

        # 2.1 SANITIZACIÓN PII (Fail-Closed Implementation)
        # 2.1 SANITIZACIÓN PII (Fail-Closed Implementation)
        try:
            # Intentamos limpiar los mensajes.
            # Si advanced_redact_pii falla (ej: SpaCy no carga), lanzará ValueError.
            # OPTIMIZACIÓN ASYNC: Ejecutamos en Threadpool para no bloquear EventLoop
            loop = asyncio.get_running_loop()
            messages_safe = []
            
            for m in messages_raw:
                content = m.get("content", "")
                # Offload CPU-bound task to thread pool
                safe_content = await loop.run_in_executor(None, advanced_redact_pii, content)
                messages_safe.append({"role": m["role"], "content": safe_content})
                
        except ValueError as e:
            # CAPTURA DEL FAIL-CLOSED
            # Si el PII Guard falla, detenemos todo. No contactamos al LLM.
            logger.critical(f"⛔ CRITICAL SECURITY FAILURE: {str(e)}")
            raise HTTPException(
                status_code=503, # Service Unavailable
                detail="AgentShield Security Layer is currently unavailable. Request blocked for safety."
            )

        # --- SEMANTIC CACHE CHECK (ZERO COST) ---
        if messages_safe:
            user_prompt = messages_safe[-1].get("content", "")
            
            # 1. Búsqueda Vectorial (Filtro 1)
            cache_data = await get_semantic_cache_full_data(user_prompt)
            
            if cache_data:
                # 2. RERANKING LÓGICO (Filtro 2 - Nivel Dios)
                is_valid = await verify_cache_logic(user_prompt, cache_data['prompt'])
                
                if is_valid:
                    cached_res = cache_data['response']
                    tokens_saved = len(cached_res) // 4
                    
                    background_tasks.add_task(
                        record_transaction,
                        tenant_id=tenant_id,
                        cost_center_id=cost_center_id,
                        cost_real=0.0, 
                        cache_hit=True,
                        tokens_saved=tokens_saved,
                        metadata={
                            "trace_id": trace_id,
                            "cache_status": "VERIFIED_HIT",
                            "processed_in": CURRENT_REGION,
                            "model": body.get("model"),
                            "verdict": "Verified by Reranker"
                        }
                    )
                    
                    return {
                        "choices": [{"message": {"content": cached_res}, "finish_reason": "stop"}],
                        "usage": {"total_tokens": 0, "cache_status": "VERIFIED_HIT"},
                        "model": body.get("model")
                    }

        # --- SEMANTIC FIREWALL & PARALLEL EXECUTION (HIGH PERFORMANCE) ---
        
        # 3. Estimación de Input
        est_input = sum([len(m.get("content", "")) for m in messages_safe]) // 4
        
        # 4. Preparar parámetros del body
        extra_body = {k: v for k, v in body.items() if k not in ["model", "messages", "stream"]}

        # 5. Dynamic Key (Infisical Pattern)
        provider_name = model.split("/")[0].upper() if "/" in model else "OPENAI"
        secret_name = f"LLM_KEY_{provider_name}"
        api_key = get_secret(secret_name)
        
        # --- PARALLEL LAUNCH ---
        # Lanzamos seguridad y generación a la vez.
        guard_task = asyncio.create_task(detect_risk_with_llama_guard(messages_safe))
        
        try:
            llm_task = asyncio.create_task(acompletion(
                model=model,
                messages=messages_safe,
                stream=stream,
                api_key=api_key,
                **extra_body
            ))
            
            # --- 200ms HARD ENFORCEMENT ---
            try:
                # Esperamos al guard con un timeout estricto
                is_unsafe = await asyncio.wait_for(asyncio.shield(guard_task), timeout=0.2)
                
                if is_unsafe:
                    llm_task.cancel()
                    span.set_attribute("security.blocked", True)
                    raise HTTPException(status_code=403, detail="AgentShield Security: Request blocked by Safety Layer.")
            
            except asyncio.TimeoutError:
                # 2026 "No-Fissure" Policy: Si el guard es lento, CANCELAMOS por precaución (Fail-Closed).
                llm_task.cancel()
                logger.warning("⏱️ Security Timeout: Blocking request for safety.")
                span.set_attribute("security.timeout_blocked", True)
                raise HTTPException(status_code=403, detail="Security Timeout: Safety check exceeded latency limits.")

            # --- AUDITORÍA BACKGROUND ---
            # Si pasó el timeout (wait_for devolvió, pero no era unsafe), ya sabemos que es seguro.
            
            # --- RESPONSE HANDLING ---
            response = await llm_task
            
            if stream:
                # CASO STREAMING
                async def stream_generator(resp_iterator):
                    stream_cost = 0.0
                    full_content = ""
                    try:
                        async for chunk in resp_iterator:
                            if hasattr(chunk, "_hidden_params"):
                                stream_cost = max(stream_cost, chunk._hidden_params.get("response_cost", 0.0))
                            delta = chunk.choices[0].delta.content or ""
                            full_content += delta
                            yield f"data: {json.dumps(chunk.json())}\n\n"
                        yield "data: [DONE]\n\n"
                    finally:
                        final_cost = stream_cost
                        if final_cost <= 0:
                             final_cost = estimator.estimate_cost(model, "COMPLETION", input_unit_count=est_input + (len(full_content)//4))
                        
                        latency_ms = (time.time() - start_time) * 1000
                        await record_transaction(
                            tenant_id, cost_center_id, final_cost, 
                            {"model": model, "mode": "stream", "trace_id": trace_id, "latency_ms": latency_ms, "processed_in": CURRENT_REGION}
                        )

                return StreamingResponse(stream_generator(response), media_type="text/event-stream")
            
            else:
                # CASO NO-STREAM
                cost_usd = response._hidden_params.get("response_cost", 0.0)
                raw_content = response.choices[0].message.content
                
                # --- BONUS: OUTPUT PII SCRUBBING (DLP) ---
                # Limpiamos la SALIDA del LLM para evitar fugas de datos generados o alucinados
                if raw_content:
                    final_content = await loop.run_in_executor(None, advanced_redact_pii, raw_content)
                    # Actualizamos el objeto de respuesta
                    response.choices[0].message.content = final_content
                else:
                    final_content = ""
                
                # Cache Setup
                if messages_safe and final_content:
                    background_tasks.add_task(set_semantic_cache, messages_safe[-1].get("content", ""), final_content)

                latency_ms = (time.time() - start_time) * 1000
                
                # Record Transaction
                if cost_usd <= 0:
                    cost_usd = estimator.estimate_cost(model, "COMPLETION", input_unit_count=est_input + (len(final_content)//4))
                
                # --- OBSERVABILIDAD DE NEGOCIO (Green IT + Compliance) ---
                total_tokens = (est_input * 4) + (len(final_content)//4) # Aprox
                carbon_g = calculate_footprint(model, CURRENT_REGION, total_tokens)
                
                # INYECCIÓN OTEL (Grafana Magic)
                span.set_attribute("carbon.emissions_g", carbon_g)
                span.set_attribute("energy.kwh_estimated", (total_tokens/1000.0)*0.001)
                
                span.set_attribute("compliance.data_residency", CURRENT_REGION)
                span.set_attribute("compliance.actor_id", tenant_id)
                span.set_attribute("compliance.pii_scrubbed", True)
                span.set_attribute("compliance.eu_ai_act_risk", "General Purpose") # Idealmente vendría de metadata

                background_tasks.add_task(
                    record_transaction, tenant_id, cost_center_id, cost_usd, 
                    {"model": model, "mode": "proxy", "trace_id": trace_id, "latency_ms": latency_ms, "processed_in": CURRENT_REGION, "carbon_g": carbon_g}
                )
                return JSONResponse(content=json.loads(response.json()))

        except HTTPException:
            raise
        except Exception as e:
            record_safe_exception(span, e)
            raise HTTPException(status_code=502, detail=f"Provider Error: {str(e)}")
