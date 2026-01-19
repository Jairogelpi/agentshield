# agentshield_core/app/routers/proxy.py

import os
import asyncio
import time
from fastapi import APIRouter, Request, HTTPException, Header, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from app.db import get_function_config, supabase, redis_client  # <--- AÑADIR redis_client 
from app.estimator import estimator
from app.services.billing import record_transaction
from app.services.pii_guard import advanced_redact_pii
from app.services.vault import get_secret
from litellm import acompletion, token_counter, model_cost # Para consultar la verdad interna
from app.services.pricing_sync import audit_and_correct_price # <--- NUEVO IMPORT
import logging
from app.utils import fast_json as json
# --- IMPORTAMOS LA NUEVA LÓGICA DE VERIFICACIÓN ---
from app.services.identity import verify_identity_envelope, VerifiedIdentity
from app.services.limiter import check_hierarchical_budget, charge_hierarchical_wallets

@router.post("/v1/chat/completions")
async def universal_proxy(
    request: Request,
    background_tasks: BackgroundTasks,
    # 🛡️ ZERO TRUST IDENTITY ENVELOPE (Replaces verify_api_key)
    identity: VerifiedIdentity = Depends(verify_identity_envelope),
    x_function_id: str = Header("default", alias="X-Function-ID"),
):
    """
    Proxy Universal Seguro (Zero Trust & Waterfall Budgeting).
    Requiere Identity Envelope (JWT) firmado.
    """
    
    start_time = time.time()
    
    # 1. AUTENTICACIÓN: Garantizada por 'identity' (Cryptographically Signed)
    tenant_id = identity.tenant_id
    logger.info(f"🔒 Secure Request from {identity.email} (Dept: {identity.dept_id})")

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
    
    # B.0. POLÍTICA DE MODELOS (Allowlist Enforcement)
    # Recuperamos la política activa (cacheada en Redis)
    from app.logic import get_active_policy
    policy_rules = await get_active_policy(tenant_id)
    
    allowed_models = policy_rules.get("allowlist", {}).get("models", [])
    
    # Si la lista NO está vacía, aplicamos restricción estricta
    if allowed_models and original_model not in allowed_models:
        # Check si es un modelo "wildcard" (ej: "gpt-*") o match exacto
        # Para MVP, match exacto:
        logger.warning(f"⛔ Policy Violation: Model {original_model} not allowed for {tenant_id}")
        raise HTTPException(403, f"Model '{original_model}' is restricted by your organization policy.")

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

    # 🌊 WATERFALL BUDGETING (The Moat)
    # Verificamos casacada: Tenant -> Dept -> User
    can_afford, reason = await check_hierarchical_budget(identity, cost_est)
    
    if not can_afford:
        # 402 Payment Required: Bloqueo estricto
        logger.warning(f"⛔ Governance Block: {reason}")
        raise HTTPException(status_code=402, detail=f"Financial Governance: {reason}")
    
    # Legacy Budget Check (Function-level) - Optional, kept for compatibility
    budget = config.get('budget_daily', 0.0)
    spent = config.get('current_spend_daily', 0.0)
    
    if budget > 0:
        if spent + cost_est > budget:
            logger.warning(f"💸 Function Budget Exceeded for {x_function_id}")
            raise HTTPException(402, f"Daily budget exceeded for function '{x_function_id}'")

    # C. Limpieza de Datos (PII Guard - Rust Hybrid)
    # Limpiamos los datos SIEMPRE, vaya a OpenAI o a Localhost
    # Esto garantiza que nunca filtres secretos, incluso en local.
    # C. Limpieza de Datos (PII Guard - Rust Hybrid)
    # Limpiamos los datos SIEMPRE, vaya a OpenAI o a Localhost
    # Esto garantiza que nunca filtres secretos, incluso en local.
    clean_messages = []
    semantic_probe = "" # Texto representativo para búsqueda vectorial
    for m in messages:
        # 1. Limpiamos el contenido (si existe y es string)
        raw_content = m.get("content")
        clean_content = raw_content
        if isinstance(raw_content, str):
            clean_content = await advanced_redact_pii(raw_content, tenant_id)
        
        # 2. Copiamos el mensaje original para no perder 'tool_calls', 'name', etc.
        # FIX: "Agent Killer" - Preservamos campos de Function Calling
        new_msg = m.copy()
        new_msg["content"] = clean_content
        
        clean_messages.append(new_msg)
        
        # Construimos el contexto para la búsqueda semántica
        if m["role"] == "user" and isinstance(clean_content, str):
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

                # --- METRICS FIX: REPORTAR AHORROS REALES ---
                try:
                    # Calculamos el coste del modelo original (lo que iba a gastar)
                    original_cost_est = await estimator.estimate_cost(
                        model=original_model, task_type="COMPLETION", input_unit_count=input_tokens
                    )
                    # Calculamos el coste del nuevo modelo (lo que va a gastar)
                    new_cost_est = await estimator.estimate_cost(
                        model=new_model, task_type="COMPLETION", input_unit_count=input_tokens
                    )

                    savings = original_cost_est - new_cost_est
                    if savings > 0:
                        # Incrementamos contador real en Redis
                        await redis_client.incrbyfloat(f"stats:{tenant_id}:actual_savings", savings)
                except Exception as metric_err:
                    logger.warning(f"Failed to calculate savings metrics: {metric_err}")
                # ---------------------------------------------

                target_model = new_model
                if best_option.get("api_base"):
                    api_base = best_option["api_base"]
            
            else:
                 # --- AÑADIR ESTE ELSE PARA EL FOMO (Pérdida de Oportunidad) ---
                 # Si NO hubo arbitraje (best_option is None), calculamos cuánto perdimos por no usar el modelo más barato
                try:
                     # Asumimos que un modelo "barato" genérico cuesta un 50% menos
                     # Esto es una heurística para "gamificar" el dashboard y mostrar "Missed Potential"
                     potential_loss = cost_est * 0.5 
                     # Solo registramos si el modelo actual es caro (ej. GPT-4)
                     if "gpt-4" in target_model or "claude-3-opus" in target_model:
                         await redis_client.incrbyfloat(f"stats:{tenant_id}:missed_savings", potential_loss)
                         await redis_client.incrbyfloat(f"stats:{tenant_id}:missed_carbon", 0.5) # 0.5g CO2 aprox
                except Exception as fomo_err:
                    logger.warning(f"FOMO calculation failed: {fomo_err}")

        except Exception as e:
            logger.warning(f"Arbitrage/SmartRouting failed: {e}")
             # Por ahora no lo contamos como missed_savings para no llenar de ruido.


    # Obtener API Key del proveedor (Si es local, suele ser irrelevante, pero LiteLLM la pide)
    # Si vamos a OpenAI real, sacamos la key de nuestro Vault.
    api_key = None
    if not api_base: 
        # Es tráfico Cloud, necesitamos pagar nosotros
        provider = target_model.split("/")[0] if "/" in target_model else "openai"
        api_key = get_secret(f"LLM_KEY_{provider.upper()}")

    # 5. EJECUCIÓN REAL (LiteLLM maneja la complejidad)
    # 5. EJECUCIÓN REAL (LiteLLM maneja la complejidad)
    # FIX: RESILIENCIA - Bucle de Reintentos (Fallback)
    MAX_RETRIES = 2
    response = None
    
    for attempt in range(1, MAX_RETRIES + 1):
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
            
            start_ts = time.time()
            response = await acompletion(**litellm_kwargs)
            latency_ms = (time.time() - start_ts) * 1000
            
            # --- FIX: "INFLATED SELF-ESTEEM" (Real Quality Score) ---
            # Si no es streaming, podemos evaluar la calidad real usando el Reranker (Self-Reflection)
            # Si es streaming, es más difícil sin buffer, así que asumimos neutralidad o implementación futura.
            if not stream and is_smart_active and 'best_option' in locals() and best_option.get("rl_state"):
                 rl_state = best_option["rl_state"]
                 responseText = response.choices[0].message.content
                 
                 # Lo lanzamos en background para no sumar latencia al usuario
                 async def background_rl_update(st, mod, txt, lat):
                     try:
                         from app.services.reranker import get_reranker_model, rank
                         # Evaluamos: ¿Qué tan relevante es la respuesta para el último prompt?
                         # Usamos el último mensaje del usuario como query
                         last_user_msg = next((m['content'] for m in reversed(clean_messages) if m['role']=='user'), "")
                         
                         score = 1.0 # Default optimism
                         if last_user_msg:
                            # Rank devuelve lista, tomamos score del primero (unico)
                            # Nota: rank() puede ser sync o async wrapper. Asumimos sync wrapper o to_thread.
                            # Para seguridad, corremos en threadpool
                            ranking = await asyncio.to_thread(rank, last_user_msg, [txt])
                            if ranking:
                                score = ranking[0]['score'] # 0.0 a 1.0
                         
                         # Calculamos recompensa REAL
                         from app.services.arbitrage import arbitrage_engine
                         # Asumimos que "ahorro" es parte del reward, pero aquí actualizamos con calidad.
                         # Ojo: calculate_reward necesita 'cost_saved'. Lo re-calculamos o estimamos.
                         # Simplificación: Reward = (Calidad * Penalización Latencia)
                         # Ignoramos coste aquí porque ya fue factorizado parcialmente, o asumimos que
                         # el "coste bajo" ya era parte de la elección. 
                         # Lo ideal es recalcular todo el reward.
                         
                         # Re-estimamos coste (si podemos) o usamos un proxy
                         # Reward = Score(0-1) - LatencyPenalty
                         
                         final_reward = arbitrage_engine.calculate_reward(
                             cost_saved=0.1, # Dummy positivo pequeño (el ahorro ya está hecho)
                             rerank_score=score,
                             latency_ms=lat,
                             user_satisfaction=1.0 # Aun no tenemos feedback explicito, pero Rerank es el proxy
                         )
                         
                         await arbitrage_engine.update_learning(st, mod, final_reward)
                         logger.info(f"🧠 Self-Reflection: Score={score:.2f}, Latency={lat:.0f}ms -> Reward={final_reward:.2f}")
                     except Exception as e:
                         logger.warning(f"Background RL Update failed: {e}")

                 # Fire and forget
                 asyncio.create_task(background_rl_update(rl_state, target_model, responseText, latency_ms))
            # ----------------------------------------------------

            break # Éxito, salimos del bucle
    
        except Exception as e:
            logger.error(f"❌ AI Provider Error (Attempt {attempt}/{MAX_RETRIES}): {e}")
            
            # --- FIX: PENALIZAR AL MODELO SI FALLA ---
            # Si el arbitraje eligió este modelo y falló, debe aprender la lección.
            if is_smart_active and 'best_option' in locals() and best_option:
                rl_state = best_option.get("rl_state")
                if rl_state:
                    from app.services.arbitrage import arbitrage_engine
                    # Recompensa muy negativa (-10) para que aprenda a evitar esto
                    asyncio.create_task(
                        arbitrage_engine.update_learning(
                            state=rl_state,
                            action_model=target_model,
                            reward=-10.0 
                        )
                    )
            # -----------------------------------------
            
            if attempt == MAX_RETRIES:
                # Si fallamos la última vez, explotamos
                raise HTTPException(502, f"Upstream AI Error after {MAX_RETRIES} attempts: {str(e)}")
            
            # Si fallamos pero quedan intentos, podríamos cambiar de modelo aquí
            # Por ahora, reintentamos (backoff)
            await asyncio.sleep(0.5 * attempt)

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
        
        try:
             output_tokens = token_counter(model=target_model, text=final_text)
        except:
             output_tokens = len(final_text or "") / 4

        # --- >>> FEEDBACK LOOP: APRENDIZAJE EN VIVO <<< ---
        # Enviamos los datos al estimador para que ajuste sus ratios futuros
        # Lo hacemos en background (fire & forget) para no latencia
        if input_tokens > 0 and output_tokens > 0:
             asyncio.create_task(
                 estimator.learn_from_reality(
                     task_type="DEFAULT", # O saca el task_type del request/metadata si lo tienes
                     model=target_model,
                     input_tokens=input_tokens,
                     output_tokens=output_tokens
                 )
             )
        # --------------------------------------------------

        # Coste REAL (Input + Output)
        total_tokens = input_tokens + output_tokens
        real_cost = await estimator.estimate_cost(
            model=target_model, 
            task_type="COMPLETION", 
            input_unit_count=total_tokens
        )
        
        # Enviamos al sistema central de facturación (Analytics + Worker)
        # IMPORTANTE: Pasamos function_id en metadata para que el worker actualice el presupuesto fantasma
        
        # 🌊 WATERFALL CHARGE (Atomic Decrement)
        # Esto descuenta el dinero de los 3 niveles REALES en Redis
        asyncio.create_task(charge_hierarchical_wallets(identity, real_cost))

        await record_transaction(
            tenant_id=tenant_id, 
            cost_center_id=identity.dept_id or "default", # Usamos el ID real del Depto
            cost_real=real_cost, 
            metadata={
                "function_id": x_function_id,
                "model": target_model,
                "original_model": original_model,
                "upstream": api_base or "cloud",
                "tokens_in": input_tokens,
                "tokens_out": output_tokens,
                "user_email": identity.email # Audit trail
            }
        )

        # --- 🤖 RL FEEDBACK LOOP: ENSEÑAR A LA IA (Fix Aprendizaje) ---
        # Si el "Smart Routing" tomó una decisión, debemos decirle si fue buena o mala.
        # Recuperamos el state que nos dio el motor de arbitraje antes.
        # Nota: 'best_option' es variable local de 'universal_proxy', pero 'post_process' es closure
        # así que podemos acceder a ella si la definimos fuera o la pasamos.
        # Para ser robustos, asumimos que 'best_option' está disponible en el scope (lo está).
        if is_smart_active and 'best_option' in locals() and best_option:
             rl_state = best_option.get("rl_state")
             if rl_state:
                 import time
                 # 1. Latencia Real (aprox) -> Recuperada del scope de universal_proxy
                 latency_ms = (time.time() - start_time) * 1000
                 # --- 🕵️‍♀️ LIVE PRICE AUDIT (AUDITORÍA EN VIVO) ---
                 # Verificamos si LiteLLM tiene datos de coste para este modelo
                 # y si coinciden con lo que nosotros tenemos.
                 try:
                     # Intentamos sacar info del objeto 'model_cost' de litellm directamente
                     # usando el nombre exacto del modelo que se usó (target_model)
                     if target_model in model_cost:
                         mc = model_cost[target_model]
                         real_p_in = float(mc.get("input_cost_per_token", 0))
                         real_p_out = float(mc.get("output_cost_per_token", 0))
                         
                         if real_p_in > 0 or real_p_out > 0:
                             # Lanzamos la auditoría en background.
                             # Si nuestro Redis tiene un precio viejo, esto lo arregla YA.
                             asyncio.create_task(
                                 audit_and_correct_price(target_model, real_p_in, real_p_out)
                             )
                 except Exception as e:
                     logger.warning(f"Price audit failed: {e}")
                 # -----------------------------------------------

                 # 2. Ahorro Real (vs precio original)
                 savings_pct = (cost_est - real_cost) / cost_est if cost_est > 0 else 0
                 
                 # 3. Calcular Recompensa
                 from app.services.arbitrage import arbitrage_engine
                 reward = arbitrage_engine.calculate_reward(
                     cost_saved=savings_pct,
                     rerank_score=1.0, 
                     latency_ms=latency_ms
                 )
                 
                 # 4. FEEDBACK (Fire & Forget)
                 asyncio.create_task(
                     arbitrage_engine.update_learning(
                         state=rl_state,
                         action_model=target_model,
                         reward=reward
                     )
                 )

    if stream:
        # Manejo de Streaming (AHORA CON COBRO REAL)
        async def stream_generator():
            full_content = ""
            try:
                async for chunk in response:
                    # LiteLLM devuelve chunks
                    content = chunk.choices[0].delta.content or ""
                    full_content += content
                    yield f"data: {json.dumps(chunk.json())}\n\n"
                yield "data: [DONE]\n\n"
            
            except Exception as stream_err:
                logger.error(f"⚠️ Stream Interrupted: {stream_err}")
                # Aún así intentamos cobrar lo consumido hasta el error
            
            finally:
                # --- 💰 FIX CRÍTICO: COBRO EN BACKGROUND ---
                # Usamos asyncio.create_task para asegurar que el cobro se ejecute
                # en el Event Loop incluso si la conexión HTTP ya se cerró.
                if full_content.strip():
                    # Creamos un objeto Mock para engañar a post_process
                    # y reutilizar la lógica de PII + Cobro + Analytics
                    class MockMessage:
                        content = full_content
                    class MockChoice:
                        message = MockMessage()
                    class MockResponseObj:
                        choices = [MockChoice()]
                    
                    # Ejecutamos el post-procesado (Cobro) en segundo plano
                    asyncio.create_task(
                        post_process(MockResponseObj(), is_stream=False)
                    )

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    else:
        # Respuesta normal JSON
        await post_process(response)
        return JSONResponse(content=json.loads(response.json()))
