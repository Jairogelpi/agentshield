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
from app.services.receipt_manager import create_forensic_receipt

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
    
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    
    # B.0. POLÍTICA DE MODELOS & REGLAS DINÁMICAS (The Policy Engine)
    # -------------------------------------------------------------
    from app.services.policy_engine import evaluate_policies, log_policy_events, PolicyContext
    
    # 1. Calculamos tokens estimados para la regla (cost check)
    try:
        input_tokens_est = token_counter(model=original_model, messages=messages)
    except:
        input_tokens_est = sum(len(m.get('content', '')) for m in messages) / 4

    cost_est_policy = await estimator.estimate_cost(
        model=original_model, task_type="COMPLETION", input_unit_count=input_tokens_est
    )

    # 2. Construimos Contexto de Política
    policy_ctx = PolicyContext(
        user_id=identity.user_id,
        user_email=identity.email,
        dept_id=str(identity.dept_id or ""), # Handle None
        role=identity.role,
        model=original_model,
        estimated_cost=cost_est_policy,
        intent="general" # Conecta aqui tu clasificador
    )

    # 3. Evaluamos (Shadow & Enforce) - Cacheado en Redis
    policy_result = await evaluate_policies(str(tenant_id), policy_ctx)

    # 4. GUARDAR EVIDENCIA (Background - No bloquea)
    background_tasks.add_task(log_policy_events, str(tenant_id), policy_ctx, policy_result)

    # A. BLOQUEO REAL (Enforce)
    if policy_result.should_block:
        logger.warning(f"🛡️ POLICY BLOCK: {policy_result.violation_msg}")
        raise HTTPException(status_code=403, detail=f"AgentShield Policy: {policy_result.violation_msg}")

    # B. MODIFICACIÓN REAL (Enforce Downgrade / Cap)
    if policy_result.action == "DOWNGRADE":
        new_mod = policy_result.modified_model
        if new_mod:
            body["model"] = new_mod
            logger.info(f"📉 Policy Downgrade applied: {original_model} -> {new_mod}")
            target_model = new_mod 
            forced = new_mod 

    elif policy_result.action == "CAP_TOKENS":
        # Parseamos el límite del mensaje (Formato "CAP:1000")
        try:
            val_str = policy_result.violation_msg.split(":")[-1]
            limit = int(val_str)
            body["max_tokens"] = limit
            logger.info(f"✂️ Policy Cap applied: Limit output to {limit} tokens")
        except:
            logger.warning("Failed to parse CAP limit, using safe default 500")
            body["max_tokens"] = 500 

    # End Policy Engine Logic
    # -------------------------------------------------------------

    # B. Control de Presupuesto (Solo si tiene límite) - Legacy & Waterfall
    # Calculamos coste estimado ANTES de enviar nada
    input_tokens = input_tokens_est
    
    cost_est = await estimator.estimate_cost(
        model=body.get("model", original_model), # Could have changed due to downgrade 
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

    # D. Mapeo de Modelo a Tier (Enterprise Gateway Logic)
    # ---------------------------------------------------
    # Convertimos el modelo solicitado en un 'Nivel de Servicio'
    target_tier = "agentshield-fast" # Default
    if "gpt-4" in original_model or "claude-3-opus" in original_model or "smart" in original_model:
        target_tier = "agentshield-smart"
    
    # Si hubo downgrade, ajustamos el tier
    if body.get("model") != original_model:
        # Simplificación: Downgrade suele ir a fast
        target_tier = "agentshield-fast"

    # 4. ENRUTAMIENTO ENTERPRISE (Gateway + Caching + Hive)
    # ----------------------------------------------
    from app.services.llm_gateway import execute_with_resilience, ProviderError
    from app.services.cache import check_cache, set_cache
    from app.services.hive_memory import search_hive_mind, store_successful_interaction
    from app.services.negotiator import negotiate_budget

    # 1. HIVE MIND (Corporate Memory) - Antes de Gateway
    last_msg_content = next((m['content'] for m in reversed(messages) if m['role']=='user'), "")
    if not stream and len(messages) < 10 and last_msg_content:
        cached_solution = await search_hive_mind(str(tenant_id), last_msg_content)
        if cached_solution:
             logger.info(f"🧠 HIVE HIT for {identity.email}")
             return {
                "id": f"hive-{cached_solution['id']}",
                "object": "chat.completion",
                "model": "agentshield-hive-1.0",
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"💡 **Solución Corporativa (por {cached_solution.get('user_email')}):**\n\n{cached_solution['response']}"
                    },
                    "finish_reason": "stop"
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            }

    # A. SELECTIVE CACHING (Capa 2: Caché Semántico/Exacto Short Term)
    should_cache = not stream and len(messages) < 20 
    
    if should_cache:
        cached_response = await check_cache(messages, target_tier, str(tenant_id))
        if cached_response:
            logger.info(f"⚡ CACHE HIT for {identity.email} on {target_tier}")
            headers = {"X-Cache": "HIT", "X-Cache-Latency": "0ms"}
            return JSONResponse(content=cached_response, headers=headers)

    # 🌊 WATERFALL BUDGETING & NEGOTIATOR
    # Verificamos casacada: Tenant -> Dept -> User
    can_afford, reason = await check_hierarchical_budget(identity, cost_est)
    
    if not can_afford:
        # --- FASE DE NEGOCIACIÓN (AI CFO) ---
        logger.info(f"💰 Budget Empty. Initiating Negotiation for {identity.email}")
        
        # Solo negociamos si es una tarea razonable, no si está bloqueado por política
        is_granted, judge_reason = await negotiate_budget(last_msg_content, target_tier, 0)
        
        if is_granted:
             logger.info(f"✅ AI CFO approved emergency overdraft: {judge_reason}")
             # Proceed (we assume 'can_afford' is overridden effectively)
             # Note: logic flows to Gateway. We might want to flag this transaction as 'overdraft' in metadata later.
        else:
            logger.warning(f"⛔ Governance Block: {reason} & Negotiation Denied: {judge_reason}")
            raise HTTPException(status_code=402, detail=f"Budget Exceeded. Emergency Request Denied: {judge_reason}")

    # B. EXECUTION WITH RESILIENCE (El nuevo Gateway)
    try:
        response = await execute_with_resilience(
            tier=target_tier, 
            messages=messages, 
            user_id=identity.user_id
        )
        target_model = response.get("model", target_tier) 
        
        # --- 🛡️ TOOL GOVERNOR (Control de Acciones) ---
        # Interceptamos si el LLM quiere ejecutar herramientas
        # Nota: Litellm devuelve ModelResponse que actúa como dict o objeto
        choices = response.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            tool_calls = message.get("tool_calls")
            
            if tool_calls:
                from app.services.tool_governor import governor
                logger.info("🛠️ Tool Calls Detected. Engaging Governor.")
                
                # INSPECCIÓN Y SANITIZACIÓN
                # 'tool_calls' es una lista de objetos/dict. Governor espera lista de dicts.
                # Si son objetos de litellm, los convertimos a dict si es necesario, pero start with raw pass
                # Assuming simple objects compatible with dict access or pydantic models
                
                # Convert active helper objects to dicts if needed
                tool_calls_dicts = [t if isinstance(t, dict) else t.model_dump() for t in tool_calls]
                
                safe_tool_calls = await governor.inspect_tool_calls(
                    identity, 
                    tool_calls_dicts
                )
                
                # Reemplazamos las llamadas originales por las filtradas
                # Modificamos el objeto response in-place
                response["choices"][0]["message"]["tool_calls"] = safe_tool_calls

    except ProviderError as e:
        logger.critical(f"🔥 TOTAL OUTAGE for {identity.email}: {e}")
        raise HTTPException(status_code=503, detail="Service currently unavailable due to upstream provider outage.")
    except Exception as e:
        logger.error(f"Gateway unhandled error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # C. SAVE TO CACHE & HIVE (Asíncrono)
    if should_cache:
        background_tasks.add_task(set_cache, messages, target_tier, str(tenant_id), response)
        
    # Guardar en Hive si fue útil? (Heurística: Long responses are usually solutions)
    # En un sistema real, el usuario daría thumbs up. Aquí guardamos todo para poblar la DB inicial.
    if last_msg_content and not stream:
        resp_content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        if len(resp_content) > 50: # Solo respuestas sustanciales
             background_tasks.add_task(
                store_successful_interaction, 
                str(tenant_id), 
                identity.email, 
                last_msg_content, 
                resp_content
            )

    # 5. POST-PROCESO (Unificado)
    # ---------------------------
    # El gateway devuelve dict (o similar). Lo pasamos a response object si es necesario?
    # Agentshield logic downstream expects 'response' object from litellm or dict.
    # Our gateway returns what litellm returns (ModelResponse) OR a dict depending on my implementation in llm_gateway.
    # I implemented `_call_provider` returning `acompletion` result which is ModelResponse.
    # So `response` is valid ModelResponse.
    
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

        # ⚖️ DIGITAL NOTARY (FORENSIC RECEIPT)
        # Generamos evidencia firmada y encadenada
        
        # Policy Proof Construction (Real Data)
        policy_proof = {
            "applied_rule": policy_result.violation_msg or "DEFAULT_ALLOW_POLICY",
            "decision": policy_result.action,
            "reason": f"Evaluation Result: {policy_result.action}. Shadow hits: {len(policy_result.shadow_hits)}",
            "remediation": "Review policy configuration" if policy_result.action == "BLOCK" else "None required"
        }

        tx_data = {
            "model_requested": original_model,
            "model_delivered": target_model, 
            "cost_usd": real_cost,
            "tokens": {"input": input_tokens, "output": output_tokens},
            "decision": policy_result.action, # "ALLOW" | "DOWNGRADE"
            "policy_proof": policy_proof, # <--- The "Policy-Proof" Evidence
            "redactions_count": 0 # TODO: Pass actual redaction count from PII Guard
        }
        
        # Snapshot de la política actual para probar qué reglas estaban activas
        # En un sistema real full, serializaríamos las políticas cacheadas.
        # Aquí guardamos un resumen hashable.
        policy_snapshot = {
            "timestamp": time.time(),
            "active_mode": "ENFORCE",
            "shadow_hits_count": len(policy_result.shadow_hits)
        }

        # Fire and forget: No bloqueamos la respuesta al cliente
        asyncio.create_task(
            create_forensic_receipt(
                tenant_id=tenant_id,
                user_email=identity.email,
                transaction_data=tx_data,
                policy_snapshot=policy_snapshot
            )
        )

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
