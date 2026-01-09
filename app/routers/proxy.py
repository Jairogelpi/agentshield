# agentshield_core/app/routers/proxy.py
import os
import json
import asyncio
import time
import logging
from fastapi import APIRouter, Request, Header, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from litellm import acompletion 
from app.routers.authorize import get_tenant_from_header
from app.services.billing import record_transaction
from app.estimator import estimator
from app.db import redis_client, supabase
from app.limiter import limiter
from app.logic import verify_residency
from app.services.cache import get_semantic_cache_full_data, set_semantic_cache
from app.services.reranker import verify_cache_logic
from app.services.vault import get_secret
from app.services.pii_guard import advanced_redact_pii
from app.services.carbon import calculate_footprint
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

logger = logging.getLogger("agentshield.security")
tracer = trace.get_tracer(__name__)
CURRENT_REGION = os.getenv("SERVER_REGION", "eu")

# --- HELPER: Obtener Cost Center por defecto (FALTABA ESTO) ---
async def get_proxy_cost_center(tenant_id: str) -> str:
    """
    Busca el centro de costes por defecto del tenant para imputar el gasto.
    Cacheado en Redis por 1 hora.
    """
    # 1. Try Cache
    cache_key = f"tenant:default_cc:{tenant_id}"
    cached = redis_client.get(cache_key)
    if cached: return cached

    # 2. DB Lookup (El primero que encuentre, generalmente 'Default Project')
    res = supabase.table("cost_centers").select("id").eq("tenant_id", tenant_id).limit(1).execute()
    
    if res.data:
        cc_id = res.data[0]['id']
        redis_client.setex(cache_key, 3600, cc_id)
        return cc_id
    
    # 3. Fallback de emergencia (crear uno al vuelo o error)
    raise HTTPException(status_code=400, detail="No active Cost Center found for this Tenant. Please create one in Dashboard.")

# --- HELPER: Trazas Seguras ---
def record_safe_exception(span, e: Exception):
    safe_msg = advanced_redact_pii(str(e))
    span.add_event("exception", {
        "exception.type": type(e).__name__,
        "exception.message": safe_msg
    })
    span.set_status(Status(StatusCode.ERROR, safe_msg))

# --- SEMANTIC FIREWALL ---
async def detect_risk_with_llama_guard(messages: list) -> bool:
    with tracer.start_as_current_span("security_guard_check") as span:
        try:
            response = await acompletion(
                model="groq/llama-guard-3-8b", 
                messages=messages,
                temperature=0.0 
            )
            verdict = response.choices[0].message.content.lower()
            if "unsafe" in verdict:
                logger.error(f"🔥 Security Threat Blocked: {verdict}")
                return True # UNSAFE
            return False # SAFE
        except Exception as e:
            record_safe_exception(span, e)
            logger.critical(f"🚨 Safety Layer Failure (Fail-Closed): {e}")
            return True # Fail-Closed

router = APIRouter(tags=["Universal Proxy"])

@router.post("/v1/chat/completions")
@limiter.limit("600/minute")
async def universal_proxy(
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: str = Header(...)
):
    with tracer.start_as_current_span("universal_proxy_flow") as span:
        trace_id = format(span.get_span_context().trace_id, '032x')
        start_time = time.time()

        # 1. AUTENTICACIÓN
        try:
            as_key = authorization.replace("Bearer ", "").strip()
            tenant_id = await get_tenant_from_header(x_api_key=as_key)
            await verify_residency(tenant_id)
            
            # ✅ AHORA SÍ FUNCIONARÁ ESTA LLAMADA
            cost_center_id = await get_proxy_cost_center(tenant_id)
            
        except Exception as e:
            if isinstance(e, HTTPException): raise e
            raise HTTPException(status_code=401, detail="Invalid AgentShield API Key")

        # 2. LEER Y SANITIZAR
        body = await request.json()
        model = body.get("model") 
        messages_raw = body.get("messages", [])
        stream = body.get("stream", False)

        try:
            loop = asyncio.get_running_loop()
            messages_safe = []
            for m in messages_raw:
                content = m.get("content", "")
                safe_content = await loop.run_in_executor(None, advanced_redact_pii, content)
                messages_safe.append({"role": m["role"], "content": safe_content})
        except ValueError as e:
            logger.critical(f"⛔ PII GUARD FAILURE: {e}")
            raise HTTPException(status_code=503, detail="Security Layer Unavailable")

        # 3. SEMANTIC CACHE (Reranker)
        if messages_safe:
            user_prompt = messages_safe[-1].get("content", "")
            cache_data = await get_semantic_cache_full_data(user_prompt)
            
            if cache_data:
                is_valid = await verify_cache_logic(user_prompt, cache_data['prompt'])
                if is_valid:
                    cached_res = cache_data['response']
                    background_tasks.add_task(
                        record_transaction,
                        tenant_id=tenant_id,
                        cost_center_id=cost_center_id,
                        cost_real=0.0, 
                        cache_hit=True,
                        tokens_saved=len(cached_res)//4,
                        metadata={"trace_id": trace_id, "cache_status": "VERIFIED_HIT", "processed_in": CURRENT_REGION}
                    )
                    return {
                        "choices": [{"message": {"content": cached_res}, "finish_reason": "stop"}],
                        "usage": {"total_tokens": 0, "cache_status": "VERIFIED_HIT"},
                        "model": model
                    }

        # 4. EJECUCIÓN PARALELA (LLM + GUARD)
        est_input = sum([len(m.get("content", "")) for m in messages_safe]) // 4
        extra_body = {k: v for k, v in body.items() if k not in ["model", "messages", "stream"]}
        
        provider_name = model.split("/")[0].upper() if "/" in model else "OPENAI"
        api_key = get_secret(f"LLM_KEY_{provider_name}")
        
        guard_task = asyncio.create_task(detect_risk_with_llama_guard(messages_safe))
        
        try:
            llm_task = asyncio.create_task(acompletion(
                model=model,
                messages=messages_safe,
                stream=stream,
                api_key=api_key,
                **extra_body
            ))
            
            # Esperar seguridad (max 200ms)
            try:
                is_unsafe = await asyncio.wait_for(asyncio.shield(guard_task), timeout=0.2)
                if is_unsafe:
                    llm_task.cancel()
                    raise HTTPException(status_code=403, detail="Blocked by Safety Layer")
            except asyncio.TimeoutError:
                llm_task.cancel() # Fail-Closed
                raise HTTPException(status_code=403, detail="Security Timeout")

            response = await llm_task

            # 5. RESPUESTA Y AUDITORÍA
            if stream:
                async def stream_generator(resp_iterator):
                    full_content = ""
                    async for chunk in resp_iterator:
                        content = chunk.choices[0].delta.content or ""
                        full_content += content
                        yield f"data: {json.dumps(chunk.json())}\n\n"
                    yield "data: [DONE]\n\n"
                    
                    # Post-processing async
                    final_cost = estimator.estimate_cost(model, "COMPLETION", input_unit_count=est_input + (len(full_content)//4))
                    latency_ms = (time.time() - start_time) * 1000
                    await record_transaction(
                        tenant_id, cost_center_id, final_cost, 
                        {"model": model, "mode": "stream", "trace_id": trace_id, "latency_ms": latency_ms, "processed_in": CURRENT_REGION}
                    )

                return StreamingResponse(stream_generator(response), media_type="text/event-stream")
            
            else:
                raw_content = response.choices[0].message.content
                final_content = await loop.run_in_executor(None, advanced_redact_pii, raw_content)
                response.choices[0].message.content = final_content # DLP activo
                
                # Guardar en caché para el futuro
                if messages_safe and final_content:
                    background_tasks.add_task(set_semantic_cache, messages_safe[-1].get("content", ""), final_content)

                # Costes y Huella
                cost_usd = estimator.estimate_cost(model, "COMPLETION", input_unit_count=est_input + (len(final_content)//4))
                carbon_g = calculate_footprint(model, CURRENT_REGION, (est_input * 4) + (len(final_content)//4))
                latency_ms = (time.time() - start_time) * 1000

                background_tasks.add_task(
                    record_transaction, tenant_id, cost_center_id, cost_usd, 
                    {"model": model, "mode": "proxy", "trace_id": trace_id, "latency_ms": latency_ms, "processed_in": CURRENT_REGION, "carbon_g": carbon_g}
                )
                return JSONResponse(content=json.loads(response.json()))

        except HTTPException: raise
        except Exception as e:
            record_safe_exception(span, e)
            raise HTTPException(status_code=502, detail=f"Provider Error: {str(e)}")
