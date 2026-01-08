import os
import json
from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from litellm import acompletion 
from app.routers.authorize import get_tenant_from_header
from app.estimator import estimator
from app.db import redis_client
import re
from app.logic import create_aut_token

# --- SEMANTIC FIREWALL HELPERS ---
def detect_injection(messages: list) -> bool:
    """
    Heurística simple para detectar Prompt Injection.
    En producción, esto llamaría a un modelo 'Guard' (ej: Llama-Guard, Lakera).
    """
    # Patrones sospechosos básicos (MVP)
    forbidden_patterns = ["ignore all previous instructions", "system override", "pwned"]
    
    combined_text = " ".join([m.get("content", "").lower() for m in messages])
    
    for pat in forbidden_patterns:
        if pat in combined_text:
            return True
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
    authorization: str = Header(...)
):
    # 1. AUTENTICACIÓN AGENTSHIELD (Tu seguridad)
    try:
        as_key = authorization.replace("Bearer ", "").strip()
        tenant_id = await get_tenant_from_header(x_api_key=as_key)
    except Exception:
         raise HTTPException(status_code=401, detail="Invalid AgentShield API Key")

    # 2. LEER PETICIÓN (Agnóstica)
    body = await request.json()
    model = body.get("model") # El usuario pide "claude-3-opus", "gemini-pro", "ollama/llama3"
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    # --- SEMANTIC FIREWALL (AGENT OPS) ---
    
    # A. Check Prompt Injection
    if detect_injection(messages):
        # Bloquear inmediatamente. No gastar tokens.
        raise HTTPException(status_code=403, detail="Security Alert: Potential Prompt Injection Detected.")

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
                # Llamada universal
                response = await acompletion(
                    model=model, 
                    messages=messages,
                    stream=True,
                    **extra_body
                    # Nota: LiteLLM leerá las KEYS de las vars de entorno globales de este proceso/contenedor.
                )
                
                async for chunk in response:
                    # LiteLLM ya devuelve el chunk en formato estándar OpenAI
                    # Solo tenemos que serializarlo a string para SSE
                    yield f"data: {json.dumps(chunk.json())}\n\n"
                
                yield "data: [DONE]\n\n"

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
            # cost_usd = response._hidden_params.get("response_cost", 0.0) 
            
            # IMPORTANTE: LiteLLM devuelve un objeto ModelResponse, hay que convertirlo a dict/json
            return JSONResponse(content=json.loads(response.json()))

    except Exception as e:
        # Si el proveedor falla (ej: Anthropic caído), devuelves el error tal cual
        raise HTTPException(status_code=502, detail=f"Provider Error: {str(e)}")
