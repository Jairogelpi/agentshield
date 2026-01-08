import os
import json
from fastapi import APIRouter, Request, Header, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from litellm import acompletion 
from app.routers.authorize import get_tenant_from_header
from app.services.billing import record_transaction
from app.estimator import estimator
from app.db import redis_client
import re
from app.logic import create_aut_token
from opentelemetry import trace
import time

# --- SEMANTIC FIREWALL HELPERS ---
# --- SEMANTIC FIREWALL HELPERS ---
async def detect_risk_with_llama_guard(messages: list) -> bool:
    """
    Usa Llama-Guard (via Groq/Litellm) para analizar si el prompt es seguro.
    """
    try:
        # Formateamos la consulta para Llama-Guard
        # Nota: Llama-Guard espera formato específico, pero LiteLLM suele adaptar 'messages' estándar.
        response = await acompletion(
            model="groq/llama-guard-3-8b", 
            messages=messages,
            # temperature=0.0 # Strict
        )
        
        verdict = response.choices[0].message.content.lower()
        if "unsafe" in verdict:
            print(f"🔥 Llama-Guard Alert: {verdict}")
            return True
            
        return False
        
    except Exception as e:
        # Fail-Open or Fail-Closed? 
        # Para MVP Fail-Open (loguear error pero dejar pasar) para no bloquear tráfico legítimo por error de Groq.
        # En producción High-Security: Fail-Closed (return True).
        print(f"⚠️ Firewall Error (Llama-Guard): {e}")
        return False


def redact_pii(messages: list) -> list:
    """
    Redacta emails y tarjetas de crédito simples.
    """
    email_regex = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    # CC simple (Luhn check sería mejor)
    cc_regex = r"\b(?:\d[ -]*?){13,16}\b" 

    new_messages = []
    for m in messages:
        content = m.get("content", "")
        # Redactar
        content = re.sub(email_regex, "[EMAIL_REDACTED]", content)
        content = re.sub(cc_regex, "[CC_REDACTED]", content)
        
        new_messages.append({**m, "content": content})
        
    return new_messages

router = APIRouter(tags=["Universal Proxy"])

# Este proxy acepta peticiones en formato estándar y las enruta a CUALQUIER proveedor
# Soportados: OpenAI, Anthropic, Google Vertex, AWS Bedrock, Ollama, HuggingFace, etc.

@router.post("/v1/chat/completions")
async def universal_proxy(
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: str = Header(...)
):
    # Obtener el contexto de traza actual generado por el middleware
    current_span = trace.get_current_span()
    if current_span and current_span.get_span_context().is_valid:
        trace_id = format(current_span.get_span_context().trace_id, '032x')
    else:
        # Fallback si no hay OTEL activo
        trace_id = "no-trace"
    
    start_time = time.time()

    # 1. AUTENTICACIÓN AGENTSHIELD (Tu seguridad)
    try:
        as_key = authorization.replace("Bearer ", "").strip()
        tenant_id = await get_tenant_from_header(x_api_key=as_key)
        # 1.1 Obtener Cost Center por defecto (Para facturación)
        cost_center_id = await get_proxy_cost_center(tenant_id)
    except Exception:
         raise HTTPException(status_code=401, detail="Invalid AgentShield API Key")

    # 2. LEER PETICIÓN (Agnóstica)
    body = await request.json()
    model = body.get("model") # El usuario pide "claude-3-opus", "gemini-pro", "ollama/llama3"
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    # --- SEMANTIC FIREWALL (AGENT OPS) ---
    
    # --- SEMANTIC FIREWALL (AGENT OPS) ---
    
    # A. Check Prompt Injection (AI Powered)
    is_unsafe = await detect_risk_with_llama_guard(messages)
    
    if is_unsafe:
        # Bloquear inmediatamente. No gastar tokens.
        # TODO: Registrar incidente en DB (auditoría de seguridad)
        raise HTTPException(status_code=403, detail="Security Alert: Request blocked by AgentShield AI Safety Layer.")

    # B. PII Redaction (Sanitization)
    # Modificamos los mensajes al vuelo para proteger datos sensibles
    messages = redact_pii(messages)
    
    # 3. PRE-FLIGHT (Tu Estimador Universal)
    # 3. PRE-FLIGHT (Tu Estimador Universal)
    # Calculamos input aprox
    est_input = sum([len(m.get("content", "")) for m in messages]) // 4
    
    # Aquí iría tu lógica de bloqueo de presupuesto...
    # await check_budget(tenant_id, model, est_input)

    # 4. ENRUTAMIENTO UNIVERSAL (Delegamos en LiteLLM)
    # NO configuramos keys aquí manualmente. LiteLLM las leerá automáticamente del entorno del servidor.
    # Si el modelo es "ollama/llama3", LiteLLM buscará la URL de Ollama.
    # Si el modelo es "gpt-4", buscará OPENAI_API_KEY en el entorno.
    
    # Extraemos parámetros opcionales (temperature, top_p, etc)
    # Excluyendo los que ya tenemos controlados
    extra_body = {k: v for k, v in body.items() if k not in ["model", "messages", "stream"]}

    try:
        if stream:
            # CASO STREAMING: Generador asíncrono que traduce chunks al vuelo
            async def stream_generator():
                stream_cost = 0.0
                full_content = ""
                
                try:
                    # Llamada universal
                    response = await acompletion(
                        model=model, 
                        messages=messages,
                        stream=True,
                        **extra_body
                    )
                    
                    async for chunk in response:
                        # Intentar extraer coste si LiteLLM lo provee
                        # (Depende del proveedor y versión)
                        if hasattr(chunk, "_hidden_params"):
                            stream_cost = max(stream_cost, chunk._hidden_params.get("response_cost", 0.0))
                            
                        # Acumular para fallback de estimación
                        delta = chunk.choices[0].delta.content or ""
                        full_content += delta
                        
                        yield f"data: {json.dumps(chunk.json())}\n\n"
                    
                    yield "data: [DONE]\n\n"
                    
                finally:
                    # BLOCKING BUT NECESSARY: Guardar recibo al finalizar stream
                    # Si stream_cost es 0 (no soportado por proveedor), estimamos
                    final_cost = stream_cost
                    if final_cost <= 0:
                        # Fallback Estimación
                        # est_input ya lo tenemos. Output es len(full_content)
                         final_cost = estimator.estimate_cost(model, "COMPLETION", input_unit_count=est_input + (len(full_content)//4))
                    
                    # Fire & Forget en background (usando asyncio.create_task si no tenemos context manager, 
                    # pero aquí estamos en generador. Llamar a helper directo)
                    latency_ms = (time.time() - start_time) * 1000
                    await record_transaction(
                        tenant_id, 
                        cost_center_id, 
                        final_cost, 
                        {
                            "model": model, 
                            "mode": "stream",
                            "trace_id": trace_id,
                            "latency_ms": latency_ms,
                            "provider": "grafana-cloud",
                            "status": "success"
                        }
                    )

            return StreamingResponse(stream_generator(), media_type="text/event-stream")

        else:
            # CASO NO-STREAM
            response = await acompletion(
                model=model,
                messages=messages,
                stream=False,
                **extra_body
            )
            
            # LiteLLM nos da el coste real calculado por ellos (útil para auditoría)
            cost_usd = response._hidden_params.get("response_cost", 0.0)
            
            cost_usd = response._hidden_params.get("response_cost", 0.0)
            
            latency_ms = (time.time() - start_time) * 1000

            # FACTURACIÓN AUTOMÁTICA (Background)
            background_tasks.add_task(
                record_transaction, 
                tenant_id, 
                cost_center_id, 
                cost_usd, 
                {
                    "model": model, 
                    "mode": "proxy",
                    "trace_id": trace_id,
                    "latency_ms": latency_ms,
                    "provider": "grafana-cloud",
                    "status": "success"
                }
            )
            
            # IMPORTANTE: LiteLLM devuelve un objeto ModelResponse, hay que convertirlo a dict/json
            return JSONResponse(content=json.loads(response.json()))

    except Exception as e:
        # Si el proveedor falla (ej: Anthropic caído), devuelves el error tal cual
        raise HTTPException(status_code=502, detail=f"Provider Error: {str(e)}")
