import json
import logging
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from app.db import supabase, redis_client
import asyncio

logger = logging.getLogger("agentshield.policy")

class PolicyContext(BaseModel):
    user_id: str
    user_email: str
    dept_id: Optional[str]
    role: str
    model: str
    estimated_cost: float
    intent: str = "general"

class PolicyResult(BaseModel):
    should_block: bool = False
    action: str = "ALLOW"
    modified_model: Optional[str] = None
    violation_msg: Optional[str] = None
    shadow_hits: List[Dict] = [] # List of full policy dicts

async def get_cached_policies(tenant_id: str):
    """
    Estrategia de Caché: Lee de Redis. Si no hay, lee de SQL y guarda en Redis por 5 min.
    """
    cache_key = f"policies:{tenant_id}"
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"Redis fetch failed: {e}")
    
    # Fallback a DB
    res = supabase.table("policies")\
        .select("*")\
        .eq("tenant_id", tenant_id)\
        .eq("is_active", True)\
        .neq("mode", "DISABLED")\
        .order("priority")\
        .execute()
        
    policies = res.data
    
    # Guardar en Redis (TTL 300s)
    if policies:
        try:
            await redis_client.setex(cache_key, 300, json.dumps(policies))
        except Exception as e:
             logger.warning(f"Redis set failed: {e}")
             
    return policies

def evaluate_logic(rule: dict, context: PolicyContext) -> bool:
    """
    Evaluador simple de reglas JSON. 
    Soporta: max_cost, forbidden_model, intent_match
    """
    if not rule:
        return False

    # 1. Regla de Coste
    if "max_cost" in rule and context.estimated_cost > rule["max_cost"]:
        return True
        
    # 2. Regla de Modelo Prohibido (Substring match)
    if "forbidden_model" in rule and rule["forbidden_model"] in context.model:
        return True
        
    # 3. Regla de Intención (Ej: bloquear 'coding' para marketing)
    if "forbidden_intent" in rule and rule["forbidden_intent"] == context.intent:
        return True

    # 4. JSON Logic Style (para cuando el cliente manda reglas complejas)
    # Ej: { "var": "cost_usd", "op": ">", "val": 5 }
    if "var" in rule:
        var_name = rule.get("var")
        op = rule.get("op")
        val = rule.get("val")
        
        # Mapear vars del contexto
        ctx_val = None
        if var_name == "cost_usd": ctx_val = context.estimated_cost
        elif var_name == "model": ctx_val = context.model
        elif var_name == "intent": ctx_val = context.intent
        
        if ctx_val is not None:
            if op == ">" and ctx_val > val: return True
            if op == "<" and ctx_val < val: return True
            if op == "==" and ctx_val == val: return True
            if op == "in" and val in ctx_val: return True # "gpt" in "gpt-4"
        
    return False

async def evaluate_policies(tenant_id: str, context: PolicyContext) -> PolicyResult:
    policies = await get_cached_policies(tenant_id)
    result = PolicyResult()
    
    if not policies:
        return result

    for p in policies:
        # 1. Filtro de Alcance (Targeting)
        # Si target_dept_id es NULL o '*', aplica a todos. Si es específico, debe coincidir.
        if p.get('target_dept_id') and str(p['target_dept_id']) != str(context.dept_id):
           if p['target_dept_id'] != '*': continue
           
        if p.get('target_role') and p['target_role'] != '*':
            if p['target_role'] != context.role: continue
            
        # 2. Evaluar Lógica
        # DB 'rules' column maps to 'rule' arg here
        is_hit = evaluate_logic(p.get('rules', {}), context)
        
        if is_hit:
            # --- MODO SOMBRA (SHADOW) ---
            if p['mode'] == 'SHADOW':
                # Solo registramos, NO actuamos
                logger.info(f"👻 SHADOW HIT: Policy '{p['name']}' triggered for {context.user_email}")
                result.shadow_hits.append(p) # Guardamos la política entera para el log
                
            # --- MODO ACTIVO (ENFORCE) ---
            elif p['mode'] == 'ENFORCE':
                logger.warning(f"🛡️ POLICY ENFORCE: {p['name']} applied {p['action']}")
                
                if p['action'] == 'BLOCK':
                    result.should_block = True
                    result.action = "BLOCK"
                    result.violation_msg = f"Blocked by policy: {p['name']}"
                    # Bloqueo duro: dejamos de evaluar y retornamos (First Match Priority)
                    # OJO: Si quisiéramos recolectar todos los shadow hits, no deberíamos retornar aquí.
                    # Pero un bloqueo es bloqueo.
                    # Guardamos esta política como la "Culpable" en metadata si quisieramos
                    return result 
                    
                elif p['action'] == 'DOWNGRADE':
                    result.action = "DOWNGRADE"
                    # Obtenemos el modelo destino de la config
                    config = p.get('action_config') or {}
                    result.modified_model = config.get('target_model', 'agentshield-eco')
                    result.violation_msg = f"Downgraded by policy: {p['name']}"
                    # Downgrade no detiene la evaluación, podrían haber más reglas

                elif p['action'] == 'CAP_TOKENS':
                     # Nueva acción para cumplir con el Manifesto (Policy-as-Code)
                     # Permite usar el modelo pero limita el output para controlar coste/riesgo
                     result.action = "CAP_TOKENS"
                     config = p.get('action_config') or {}
                     # Usamos modified_model como campo para pasar el límite (un poco hacky pero eficiente)
                     # O mejor, extendemos PolicyResult.
                     limit = config.get('max_output_tokens', 1024)
                     result.violation_msg = f"Output capped to {limit} tokens by policy: {p['name']}"
                     # Necesitamos pasar este valor al proxy. Usaremos metadata o un campo nuevo.
                     # Por ahora, inyectamos en 'violation_msg' para que el proxy lo parsee o 
                     # (mejor) extendemos result class. Pero para no romper pydantic ahora,
                     # asumimos que si action == CAP_TOKENS, el proxy buscará el límite en la policy (que pasamos en shadow_hits? no).
                     # Simple fix: We will handle this by returning the limit in 'violation_msg' or parsing it.
                     # Better: Let's assume the Proxy reads the limit from the policy config directly? 
                     # No, proxy receives 'result'.
                     # Let's rely on 'violation_msg' storing the limit string for now: "CAP:500"
                     result.violation_msg = f"CAP:{limit}"
                     
    return result

async def log_policy_events(tenant_id: str, context: PolicyContext, result: PolicyResult):
    """
    Guarda los eventos en la DB para que el Dashboard muestre "Impacto Evitado".
    """
    events = []
    
    # 1. Loguear Shadow Hits
    for p in result.shadow_hits:
        events.append({
            "tenant_id": tenant_id,
            "policy_id": p['id'],
            "user_email": context.user_email,
            "event_type": "SHADOW_HIT",
            "action_taken": "LOGGED_ONLY",
            "metadata": {
                "cost": context.estimated_cost,
                "model": context.model,
                "intent": context.intent,
                "policy_name": p['name']
            }
        })
        
    # 2. Loguear Enforcement (si hubo acción real)
    if result.action in ['BLOCK', 'DOWNGRADE']:
        # Nota: En este diseño simplificado no tenemos el ID de la política que bloqueó en 'result' 
        # (salvo que lo agreguemos al return). Por ahora guardamos genérico.
        events.append({
            "tenant_id": tenant_id,
            "policy_id": None, 
            "user_email": context.user_email,
            "event_type": "ENFORCEMENT",
            "action_taken": result.action,
            "metadata": {"reason": result.violation_msg}
        })

    if events:
        try:
            # We don't await Supabase insert because we want fire & forget usually, 
            # but background_tasks ensures this runs in event loop. Supabase-py is synchronous unless using postgrest-py async.
            # Assuming 'supabase' is the sync client. We wrap in to_thread if needed or just run it.
            # Given existing code uses supabase.table().execute(), it is sync/blocking I/O.
            # Running this in background_tasks is fine as it won't block the main response.
            supabase.table("policy_events").insert(events).execute()
        except Exception as e:
            logger.error(f"Failed to log policy events: {e}")
