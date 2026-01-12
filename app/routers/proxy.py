# agentshield_core/app/routers/proxy.py

import os
from fastapi import APIRouter, Request, HTTPException, Header, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from app.db import get_function_config, supabase 
from app.estimator import estimator
from app.services.billing import record_transaction
from app.services.pii_guard import advanced_redact_pii
from app.services.vault import get_secret
from litellm import acompletion, token_counter
import logging
from app.utils import fast_json as json

# Logger configurado en main.py
logger = logging.getLogger("agentshield.proxy")

router = APIRouter(tags=["Universal Proxy"])

@router.post("/v1/chat/completions")
async def universal_proxy(
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: str = Header(None),
    x_function_id: str = Header("default", alias="X-Function-ID"), # <--- LA LLAVE MAESTRA
):
    """
    Proxy Universal que controla CUALQUIER código cliente mediante 'X-Function-ID'.
    Maneja tráfico Online (OpenAI) y Local (Ollama/LMStudio).
    """
    
    # 1. AUTENTICACIÓN (Tenant ID)
    if not authorization:
        raise HTTPException(401, "Missing API Key")
    # Asumimos que la key es el Tenant ID directamente o un token simple para esta demo.
    # En prod real validariamos key contra tabla tenants.
    tenant_id = authorization.replace("Bearer ", "").strip()

    # 2. AUTODESCUBRIMIENTO (La Magia)
    # Buscamos la configuración específica para esta función/script del cliente
    # Usamos la función optimizada con caché Redis que hicimos en db.py
    config = await get_function_config(tenant_id, x_function_id)

    if not config:
        # Si es la primera vez que vemos este ID, lo registramos automáticamente
        # Esto permite "Lazy Registration" desde el código del cliente.
        try:
             # Insertamos en Supabase
             new_conf = supabase.table("function_configs").insert({
                 "tenant_id": tenant_id,
                 "function_id": x_function_id,
                 "is_active": True
             }).execute()
             if new_conf.data:
                config = new_conf.data[0]
                logger.info(f"✨ New Function Discovered: {x_function_id} for Tenant {tenant_id[:4]}")
        except Exception as e:
             # Si falla (ej: race condition), intentamos leer de nuevo
             logger.warning(f"Registration race condition: {e}")
             config = await get_function_config(tenant_id, x_function_id)
        
        if not config:
             # Si aun asi falla, permitimos tráfico default pero sin persistencia (Safety Fallback)
             config = {"is_active": True, "budget_daily": 0.0, "current_spend_daily": 0.0}

    # 3. APLICAR REGLAS DE HIERRO (Control Total)
    
    # A. Interruptor de Apagado (Kill Switch)
    if not config.get('is_active', True):
        raise HTTPException(403, f"Function '{x_function_id}' is disabled by admin.")

    # Leemos el cuerpo de la petición
    body = await request.json()
    original_model = body.get("model")
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    # B. Control de Presupuesto (Solo si tiene límite)
    # Calculamos coste estimado ANTES de enviar nada
    # Usamos litellm tokenizer para mayor precisión
    try:
        input_tokens = token_counter(model=original_model, messages=messages)
    except:
        input_tokens = sum(len(m.get('content', '')) for m in messages) / 4 # Heuristica

    cost_est = await estimator.estimate_cost(
        model=original_model, 
        task_type="COMPLETION", 
        input_unit_count=input_tokens
    )
    
    budget = config.get('budget_daily', 0.0)
    spent = config.get('current_spend_daily', 0.0)
    
    if budget > 0:
        if spent + cost_est > budget:
            logger.warning(f"💸 Budget Exceeded for {x_function_id}")
            raise HTTPException(402, f"Daily budget exceeded for '{x_function_id}'")

    # C. Limpieza de Datos (PII Guard - Rust Hybrid)
    # Limpiamos los datos SIEMPRE, vaya a OpenAI o a Localhost
    # Esto garantiza que nunca filtres secretos, incluso en local.
    clean_messages = []
    semantic_probe = "" # Texto representativo para búsqueda vectorial
    for m in messages:
        clean_content = await advanced_redact_pii(m.get("content", ""), tenant_id)
        clean_messages.append({"role": m["role"], "content": clean_content})
        # Construimos el contexto para la búsqueda semántica
        if m["role"] == "user":
            semantic_probe += f"{clean_content}\n"
    
    # --- ⚡ HELICONE KILLER: SEMANTIC CACHE LAYER ⚡ ---
    from app.services.cache import get_semantic_cache, set_semantic_cache
    
    # Solo intentamos caché si no es streaming (por simplicidad MVP) y hay probe
    cache_hit = None
    if semantic_probe.strip():
        cache_hit = await get_semantic_cache(semantic_probe.strip(), threshold=0.92, tenant_id=tenant_id)
        
    if cache_hit:
        logger.info(f"⚡ CACHE HIT for {x_function_id} (Tenant: {tenant_id})")
        # Devolvemos respuesta inmediata (Simulando estructura de OpenAI)
        cached_response = {
            "id": "cache-hit-" + x_function_id,
            "object": "chat.completion",
            "created": 1234567890,
            "model": "semantic-cache",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": cache_hit
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }
        # Headers para que el cliente sepa que fue caché
        headers = {"X-Cache": "HIT", "X-Cache-Latency": "0ms"}
        return JSONResponse(content=cached_response, headers=headers)

    # D. "El Cambiazo" de Modelo (Model Swapping)
    # Si el Dashboard dice "Usa gpt-3.5" aunque el código pida "gpt-4", obedecemos al Dashboard.
    forced = config.get('force_model')
    target_model = forced if forced else original_model
    
    # 4. ENRUTAMIENTO (Híbrido: Nube vs Local)
    # Si config.upstream_url tiene valor (ej: http://localhost:11434), LiteLLM mandará ahí.
    # Si es None, LiteLLM usará la API oficial de OpenAI/Anthropic.
    api_base = config.get('upstream_url') 
    
    # --- 💰 HEDGE FUND STRATEGY: MODEL ARBITRAGE 💰 ---
    # Si no hay forzado manual y el cliente activó "Smart Routing"
    from app.services.arbitrage import get_best_provider
    
    # Asumimos que 'smart_routing_enabled' vendrá en config en el futuro. 
    # Por ahora checkeamos si existe la key o si el usuario "quiere ganar siempre" enviando header 'X-Smart-Routing'
    # o simplemente si config lo tiene (lo simularemos o confiaremos en que DB lo traerá)
    is_smart_active = config.get('smart_routing_enabled', False)
    
    if not forced and is_smart_active:
        try:
            # Buscamos la mejor oferta en el mercado AHORA MISMO
            best_option = await get_best_provider(
                target_quality=target_model,
                max_latency_ms=2000,
                messages=clean_messages # Usamos mensajes LIMPIOS para análisis (Safe)
            )
            
            if best_option:
                new_model = best_option["model"]
                logger.info(f"💰 Arbitrage Active: Swapping {target_model} -> {new_model} (Reason: {best_option.get('reason')})")
                
                # APLICAMOS EL SWAP
                target_model = new_model
                if best_option.get("api_base"):
                    api_base = best_option["api_base"]
        except Exception as arb_err:
             logger.warning(f"Arbitrage skipped due to error: {arb_err}")

    # Obtener API Key del proveedor (Si es local, suele ser irrelevante, pero LiteLLM la pide)
    # Si vamos a OpenAI real, sacamos la key de nuestro Vault.
    api_key = None
    if not api_base: 
        # Es tráfico Cloud, necesitamos pagar nosotros
        provider = target_model.split("/")[0] if "/" in target_model else "openai"
        api_key = get_secret(f"LLM_KEY_{provider.upper()}")

    # 5. EJECUCIÓN REAL (LiteLLM maneja la complejidad)
    try:
        # Preparamos argumentos para LiteLLM
        litellm_kwargs = {
            "model": target_model,
            "messages": clean_messages,
            "stream": stream,
            "api_key": api_key,
        }
        if api_base:
            litellm_kwargs["api_base"] = api_base # Redirección a Local/Privado

        response = await acompletion(**litellm_kwargs)

    except Exception as e:
        logger.error(f"❌ AI Provider Error: {e}")
        raise HTTPException(502, f"Upstream AI Error: {str(e)}")

    # 6. REGISTRAR RESULTADOS (Observabilidad & Cobro)
    
    async def post_process(response_obj, is_stream=False):
        # Calcular coste real final
        final_text = ""
        if not is_stream:
            final_text = response_obj.choices[0].message.content
            # Censuramos también la respuesta por si la IA alucina datos privados
            final_text = await advanced_redact_pii(final_text, tenant_id)
            # Reemplazamos en el objeto para devolver limpio al cliente
            response_obj.choices[0].message.content = final_text
            
            # --- 💾 INSERTAR EN CACHÉ (Learning) ---
            if semantic_probe.strip() and final_text.strip():
                 # Guardamos asíncronamente
                 asyncio.create_task(set_semantic_cache(semantic_probe.strip(), final_text, tenant_id))
        
        # Calcular tokens de salida reales
        try:
             output_tokens = token_counter(model=target_model, text=final_text)
        except:
             output_tokens = len(final_text or "") / 4

        # Coste REAL (Input + Output)
        # Nota: estimate_cost aqui se usaria para el total si le pasamos tokens totales, 
        # o sumamos in+out. Simplificamos pidiendo coste total 'como si fuera una completion de X tokens'
        # Lo ideal seria sumar input_cost + output_cost. 
        # Para simplificar y usar tools existentes:
        total_tokens = input_tokens + output_tokens
        real_cost = await estimator.estimate_cost(
            model=target_model, 
            task_type="COMPLETION", 
            input_unit_count=total_tokens
        )
        
        # Enviamos al sistema central de facturación (Analytics + Worker)
        # IMPORTANTE: Pasamos function_id en metadata para que el worker actualice el presupuesto fantasma
        await record_transaction(
            tenant_id=tenant_id, 
            cost_center_id="default_cost_center", # O podriamos sacarlo de alguna parte, default ok para proxy
            cost_real=real_cost, 
            metadata={
                "function_id": x_function_id,
                "model": target_model,
                "original_model": original_model,
                "upstream": api_base or "cloud",
                "tokens_in": input_tokens,
                "tokens_out": output_tokens
            }
        )

    if stream:
        # Manejo de Streaming (Passthrough)
        # Nota: Calcular coste exacto en stream es dificil sin acomular.
        # Aqui simplificamos: No procesamos coste en stream para esta demo o asumimos estimacion.
        # O acumulamos en el generador.
        async def stream_generator():
            full_content = ""
            async for chunk in response:
                content = chunk.choices[0].delta.content or ""
                full_content += content
                yield f"data: {json.dumps(chunk.json())}\n\n"
            yield "data: [DONE]\n\n"
            
            # Al finalizar, registramos cobro (Best Effort)
            # await post_process(MockResponse(full_content), is_stream=False) # Pseudocodigo
            # Para evitar bloquear el stream, lanzamos background task? 
            # No se puede desde generador async facilmente. 
            # Dejamos pendiente el cobro exacto de streaming para v2.
            
        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    else:
        # Respuesta normal JSON
        await post_process(response)
        return JSONResponse(content=json.loads(response.json()))
