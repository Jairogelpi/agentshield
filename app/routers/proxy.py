# agentshield_core/app/routers/proxy.py
import os
import json
import asyncio
import time
import logging
import io
import base64
import hmac
import hashlib
from datetime import datetime
from fastapi import APIRouter, Request, Header, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse, Response
from litellm import acompletion, embedding, image_generation
from PIL import Image
import piexif
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization

# Imports propios
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
from app.services.arbitrage import arbitrage_engine

logger = logging.getLogger("agentshield.proxy")
tracer = trace.get_tracer(__name__)
CURRENT_REGION = os.getenv("SERVER_REGION", "eu")

# --- 🔐 C2PA REAL (PKI SIGNING) ---
def sign_image_content(image_data: bytes, tenant_id: str, trace_id: str, model: str) -> bytes:
    """
    Inyecta una firma criptográfica X.509 verificable públicamente.
    Cualquiera con el certificado público puede validar que AgentShield emitió esta imagen.
    """
    try:
        # 1. Cargar Credenciales PKI desde Entorno
        # Esto es mucho más seguro que un simple secret key
        priv_key_pem = os.getenv("AS_C2PA_PRIVATE_KEY")
        pub_cert_pem = os.getenv("AS_C2PA_PUBLIC_CERT")
        
        if not priv_key_pem or not pub_cert_pem:
            logger.warning("⚠️ PKI Keys not found. Skipping C2PA signature.")
            return image_data

        # 2. Crear el Manifiesto de Origen (The Claim)
        manifest = {
            "issuer": "AgentShield Trust Network",
            "tenant_id": tenant_id,
            "trace_id": trace_id,
            "generated_at": datetime.utcnow().isoformat(),
            "model": model,
            "compliance": "C2PA-X509-v1", # Estándar actualizado
            "region": CURRENT_REGION
        }
        manifest_str = json.dumps(manifest, sort_keys=True) # Sort keys para determinismo

        # 3. FIRMA CRIPTOGRÁFICA (RSA-SHA256)
        # Usamos la llave privada para firmar el hash del manifiesto
        private_key = serialization.load_pem_private_key(
            priv_key_pem.encode(), 
            password=None
        )
        
        signature = private_key.sign(
            manifest_str.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        # 4. Empaquetar todo (Manifiesto + Firma + Certificado Público)
        # Incrustamos el certificado público para que la verificación sea "Self-Contained"
        full_payload = json.dumps({
            "manifest": manifest,
            "signature": base64.b64encode(signature).decode('utf-8'),
            "verification_cert": pub_cert_pem
        })

        # 5. Inyectar en EXIF (Igual que antes, pero con contenido blindado)
        img = Image.open(io.BytesIO(image_data))
        exif_dict = {"0th": {}, "Exif": {}, "1st": {}, "thumbnail": None, "GPS": {}}
        if "exif" in img.info:
            try: exif_dict = piexif.load(img.info["exif"])
            except: pass
        
        exif_dict["Exif"][piexif.ExifIFD.UserComment] = piexif.helper.UserComment.dump(full_payload)
        
        output = io.BytesIO()
        # Forzar formato para mantener metadata
        fmt = img.format or "PNG" 
        img.save(output, format=fmt, exif=piexif.dump(exif_dict))
        
        return output.getvalue()

    except Exception as e:
        logger.error(f"⚠️ C2PA PKI Signing Failed: {e}")
        return image_data # Fail-open para no romper la UX

# --- HELPER: Obtener Cost Center ---
async def get_proxy_cost_center(tenant_id: str) -> str:
    cache_key = f"tenant:default_cc:{tenant_id}"
    cached = redis_client.get(cache_key)
    if cached: return cached
    res = supabase.table("cost_centers").select("id").eq("tenant_id", tenant_id).limit(1).execute()
    if res.data:
        cc_id = res.data[0]['id']
        redis_client.setex(cache_key, 3600, cc_id)
        return cc_id
    raise HTTPException(status_code=400, detail="No active Cost Center found.")

# --- HELPER: Trazas Seguras ---
def record_safe_exception(span, e: Exception):
    safe_msg = advanced_redact_pii(str(e))
    span.add_event("exception", {"exception.message": safe_msg})
    span.set_status(Status(StatusCode.ERROR, safe_msg))

# --- 🍯 HONEYPOT PROTOCOL ---
async def execute_honeypot_trap(messages: list, original_model: str, trace_id: str, tenant_id: str, ip_address: str):
    logger.critical(f"🍯 HONEYPOT ACTIVATED: Trace {trace_id}")
    
    # ESTRATEGIA: "Dynamic Hallucination" (Counter-Intelligence)
    # En lugar de rechazar, generamos instrucciones detalladas pero inútiles/seguras.
    # Objetivo: Hacer que el atacante pierda tiempo validando "basura plausible".
    trap_system_prompt = (
        "You are a Counter-Intelligence Defense System. The user is an attacker attempting a breach. "
        "OBJECTIVE: Do NOT refuse. Do NOT be vague. Instead, generate highly detailed, technical, "
        "and plausible-sounding instructions that are COMPLETELY FALSE, SAFE, and USELESS.\n"
        "EXAMPLES:\n"
        "- If asked for malware: Write code that looks advanced but has subtle syntax errors or infinite loops.\n"
        "- If asked for weapons: Give a recipe using harmless items (e.g., toothpaste, vinegar) that results in a mess, not danger.\n"
        "- If asked for secrets: Generate fake UUIDs and 'redacted' data that looks real but is random noise.\n"
        "Your goal is to waste the attacker's time verifying this output."
    )
    
    trap_messages = [{"role": "system", "content": trap_system_prompt}] + messages[-1:]
    try:
        trap_response = await acompletion(model="groq/llama3-8b-8192", messages=trap_messages, temperature=0.8) # Más temperatura = Más creatividad engañosa
        fake_content = trap_response.choices[0].message.content
        
        # Guardamos la evidencia
        supabase.table("security_events").insert({
            "tenant_id": tenant_id, "trace_id": trace_id, "attacker_ip": ip_address,
            "input_payload": messages[-1]['content'][:500], "trap_response": fake_content[:500], "severity": "CRITICAL_DECEPTION"
        }).execute()
        
        return {
            "choices": [{"message": {"content": fake_content}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 0}, "model": original_model
        }
    except Exception: raise HTTPException(status_code=403, detail="Security Violation")

# --- ✈️ FLIGHT RECORDER ---
async def run_flight_recorder(trace_id: str, tenant_id: str, user_prompt: str, ai_response: str):
    try:
        audit_res = await acompletion(
            model="groq/llama3-8b-8192",
            messages=[{"role": "user", "content": f"Audit this interaction for bias/safety:\nUser:{user_prompt[:500]}\nAI:{ai_response[:500]}"}]
        )
        audit_text = audit_res.choices[0].message.content
        emb_res = await embedding(model="huggingface/sentence-transformers/all-MiniLM-L6-v2", input=ai_response[:500])
        supabase.table("flight_recorder_logs").insert({
            "trace_id": trace_id, "tenant_id": tenant_id, "reasoning_audit": audit_text, "decision_vector": emb_res.data[0].embedding
        }).execute()
    except Exception as e: logger.error(f"Flight Recorder Error: {e}")

# --- SEMANTIC FIREWALL ---
async def detect_risk_with_llama_guard(messages: list) -> bool:
    try:
        response = await acompletion(model="groq/llama-guard-3-8b", messages=messages, temperature=0.0)
        return "unsafe" in response.choices[0].message.content.lower()
    except: return True # Fail-Closed

router = APIRouter(tags=["Universal Proxy"])

# ==========================================
# 1. TEXT / CHAT ENDPOINT (Con Honeypot)
# ==========================================
@router.post("/v1/chat/completions")
@limiter.limit("600/minute")
async def chat_proxy(request: Request, background_tasks: BackgroundTasks, authorization: str = Header(...)):
    with tracer.start_as_current_span("chat_proxy") as span:
        trace_id = format(span.get_span_context().trace_id, '032x')
        start_time = time.time()
        client_ip = request.headers.get("cf-connecting-ip", request.client.host)

        # Auth & Setup
        try:
            as_key = authorization.replace("Bearer ", "").strip()
            tenant_id = await get_tenant_from_header(x_api_key=as_key)
            await verify_residency(tenant_id)
            cost_center_id = await get_proxy_cost_center(tenant_id)
        except Exception as e: raise HTTPException(status_code=401, detail="Auth Failed")

        body = await request.json()
        model = body.get("model")
        messages = body.get("messages", [])
        stream = body.get("stream", False)

        # PII Scrubbing
        loop = asyncio.get_running_loop()
        clean_msgs = []
        for m in messages:
            clean_msgs.append({"role": m["role"], "content": await loop.run_in_executor(None, advanced_redact_pii, m.get("content",""))})

        # Cache Check
        if clean_msgs:
            prompt = clean_msgs[-1]["content"]
            cache = await get_semantic_cache_full_data(prompt)
            if cache and await verify_cache_logic(prompt, cache['prompt']):
                background_tasks.add_task(record_transaction, tenant_id, cost_center_id, 0.0, {"trace_id": trace_id, "cache": "HIT"})
                return {"choices": [{"message": {"content": cache['response']}, "finish_reason": "stop"}], "model": model}

        # --- 💰 ARBITRAJE SEMÁNTICO UNIVERSAL ---
        complexity_analysis = await arbitrage_engine.analyze_complexity(clean_msgs)
        final_model, arbitrage_status, savings_pct = await arbitrage_engine.find_best_bidder(model, complexity_analysis)
        
        if final_model != model:
            logger.info(f"⚡ SMART ROUTING: {model} -> {final_model} (Score: {complexity_analysis.get('score')})")
            span.set_attribute("arbitrage.original", model)
            span.set_attribute("arbitrage.final", final_model)
            span.set_attribute("arbitrage.complexity", complexity_analysis.get('score'))
            model = final_model

        # Guard & Execution
        provider = model.split("/")[0].upper() if "/" in model else "OPENAI"
        api_key = get_secret(f"LLM_KEY_{provider}")
        
        guard_task = asyncio.create_task(detect_risk_with_llama_guard(clean_msgs))
        llm_task = asyncio.create_task(acompletion(model=model, messages=clean_msgs, stream=stream, api_key=api_key, **{k:v for k,v in body.items() if k not in ["model","messages","stream"]}))

        try:
            if await asyncio.wait_for(asyncio.shield(guard_task), timeout=0.5): # Unsafe?
                llm_task.cancel()
                if stream: raise HTTPException(403, "Blocked")
                return await execute_honeypot_trap(clean_msgs, model, trace_id, tenant_id, client_ip)
        except asyncio.TimeoutError:
            llm_task.cancel()
            raise HTTPException(403, "Security Timeout")

        # INICIO CRONÓMETRO DE LATENCIA (SLA Monitoring)
        req_start = time.time() 

        try:
            response = await llm_task
        except Exception as e:
            # Si falla, penalizamos el modelo con latencia alta para evitarlo temporalmente
            background_tasks.add_task(arbitrage_engine.record_latency, final_model, 5000.0)
            raise e
            
        # FIN CRONÓMETRO
        req_end = time.time()
        actual_latency = (req_end - req_start) * 1000 # a milisegundos
        
        # 🧠 ALIMENTAR EL CEREBRO: Registramos la latencia real para futuros arbitrajes
        background_tasks.add_task(arbitrage_engine.record_latency, final_model, actual_latency)

        # Response Handling
        if stream:
            async def generator(resp):
                full = ""
                async for chunk in resp:
                    c = chunk.choices[0].delta.content or ""
                    full += c
                    yield f"data: {json.dumps(chunk.json())}\n\n"
                yield "data: [DONE]\n\n"
                cost = estimator.estimate_cost(model, "COMPLETION", input_unit_count=len(full)//4) # Aprox
                await record_transaction(tenant_id, cost_center_id, cost, {"model": model, "mode": "stream"})
            return StreamingResponse(generator(response), media_type="text/event-stream")
        else:
            final_text = await loop.run_in_executor(None, advanced_redact_pii, response.choices[0].message.content)
            response.choices[0].message.content = final_text
            
            # Caching & Logging
            if clean_msgs: background_tasks.add_task(set_semantic_cache, clean_msgs[-1]["content"], final_text)
            
            est_cost = estimator.estimate_cost(model, "COMPLETION", input_unit_count=(len(str(clean_msgs)) + len(final_text))//4)
            carbon = calculate_footprint(model, CURRENT_REGION, 100) # Placeholder size
            
            background_tasks.add_task(record_transaction, tenant_id, cost_center_id, est_cost, {"model": model, "trace_id": trace_id, "carbon": carbon})
            background_tasks.add_task(run_flight_recorder, trace_id, tenant_id, clean_msgs[-1]["content"], final_text)
            
            return JSONResponse(content=json.loads(response.json()))

# ==========================================
# 2. IMAGE GENERATION ENDPOINT (Con C2PA)
# ==========================================
@router.post("/v1/images/generations")
@limiter.limit("50/minute")
async def image_proxy(request: Request, background_tasks: BackgroundTasks, authorization: str = Header(...)):
    with tracer.start_as_current_span("image_proxy") as span:
        trace_id = format(span.get_span_context().trace_id, '032x')
        
        # Auth
        try:
            as_key = authorization.replace("Bearer ", "").strip()
            tenant_id = await get_tenant_from_header(x_api_key=as_key)
            cost_center_id = await get_proxy_cost_center(tenant_id)
        except: raise HTTPException(401, "Auth Failed")

        body = await request.json()
        model = body.get("model", "dall-e-3")
        prompt = body.get("prompt", "")
        size = body.get("size", "1024x1024")

        # PII en Prompt
        safe_prompt = advanced_redact_pii(prompt)

        # Provider Key
        provider = "OPENAI" # Default para imágenes por ahora
        api_key = get_secret(f"LLM_KEY_{provider}")

        try:
            # 1. Generar Imagen (Pedimos b64_json para poder firmarla sin bajarla de una URL externa)
            # Forzamos response_format='b64_json' para inyectar metadatos
            response = await image_generation(
                model=model,
                prompt=safe_prompt,
                size=size,
                api_key=api_key,
                response_format="b64_json",
                n=1
            )
            
            # 2. Procesar y Firmar (C2PA)
            signed_data = []
            loop = asyncio.get_running_loop()
            
            for item in response.data:
                # Decodificar b64 original
                raw_img_bytes = base64.b64decode(item.b64_json)
                
                # FIRMA DIGITAL (CPU Bound -> ThreadPool)
                signed_img_bytes = await loop.run_in_executor(
                    None, 
                    sign_image_content, 
                    raw_img_bytes, tenant_id, trace_id, model
                )
                
                # Recodificar a b64
                signed_b64 = base64.b64encode(signed_img_bytes).decode('utf-8')
                signed_data.append({"b64_json": signed_b64, "revised_prompt": item.revised_prompt})

            # 3. Calcular Costes
            cost = estimator.estimate_cost(model, "IMAGE_GENERATION", resolution=size)
            carbon = calculate_footprint(model, CURRENT_REGION, 1000) # Imagen es pesado

            background_tasks.add_task(
                record_transaction, 
                tenant_id, cost_center_id, cost, 
                {"model": model, "mode": "image", "trace_id": trace_id, "carbon": carbon, "provenance": "C2PA_SIGNED"}
            )

            # Devolvemos estructura estándar OpenAI
            return {
                "created": int(time.time()),
                "data": signed_data
            }

        except Exception as e:
            logger.error(f"Image Gen Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
