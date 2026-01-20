# app/services/llm_gateway.py
import time
import random
import logging
from typing import List, Dict, Any, Optional
from litellm import completion, embedding
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Configuración de Modelos y sus Equivalencias (Fallback Chains)
# En producción, esto vendría de tu DB o Redis
from app.db import redis_client, supabase
import json

# Configuración por defecto (Fallback) solo si la DB está vacía
DEFAULT_CHAINS = {
    # Tier: "Smart" -> Prioriza inteligencia (GPT-4 class)
    "agentshield-smart": [
        {"provider": "openai", "model": "gpt-4o", "timeout": 20},     # Primario
        {"provider": "azure", "model": "azure/gpt-4o", "timeout": 20}, # Secundario (Mismo modelo, otra infra)
        {"provider": "anthropic", "model": "claude-3-opus-20240229", "timeout": 30} # Terciario (Fallback seguro)
    ],
    # Tier: "Fast" -> Prioriza velocidad/coste (GPT-3.5/Haiku class)
    "agentshield-fast": [
        {"provider": "openai", "model": "gpt-4o-mini", "timeout": 10},
        {"provider": "anthropic", "model": "claude-3-haiku-20240307", "timeout": 10},
        {"provider": "openai", "model": "gpt-3.5-turbo", "timeout": 10}
    ]
}

async def get_dynamic_config():
    """Carga configuración viva desde Redis/DB"""
    try:
        # 1. Intentar Redis
        cached = await redis_client.get("config:model_chains")
        if cached:
            return json.loads(cached)
        
        # 2. Intentar DB (Tabla system_config)
        # Asume que existe una tabla 'system_config' con {key: str, value: json}
        res = supabase.table("system_config").select("value").eq("key", "model_chains").single().execute()
        if res.data:
            config = res.data['value']
            # Guardar en Redis por 5 minutos
            await redis_client.setex("config:model_chains", 300, json.dumps(config)) 
            return config
    except Exception as e:
        logger.warning(f"Config Load Error: {e}")

    return DEFAULT_CHAINS

# Configuración Canary (Para probar cosas nuevas sin riesgo)
CANARY_CONFIG = {
    "active": True,
    "target_model": "gpt-4-turbo-preview", # El modelo experimental
    "percentage": 0.05, # 5% del tráfico
    "for_tiers": ["agentshield-smart"]
}

logger = logging.getLogger("agentshield.gateway")

class ProviderError(Exception):
    """Raised when all providers in a chain fail."""
    pass

# Decorador de Retry Inteligente (Exponential Backoff)
# Solo reintenta si es un error de red o rate limit, no si es un error de lógica.
@retry(
    stop=stop_after_attempt(2), # Reintentar cada proveedor individualmente 2 veces
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(Exception) # En prod, ser más específico (TimeoutError, etc)
)
async def _call_provider(model: str, messages: list, timeout: int, temperature: float = 0.7):
    """
    Wrapper de bajo nivel para litellm.
    """
    # Litellm maneja internamente las keys si están en ENV (OS.environ)
    # Si usas Vault, asegúrate de cargarlas antes o pasarlas aquí.
    return await completion(
        model=model,
        messages=messages,
        timeout=timeout,
        temperature=temperature
    )
    # Nota: `await completion` require litellm >= 1.0.0 async support o usar acompletion.
    # El usuario puso `completion` en el ejemplo, pero en proxy usamos `acompletion`.
    # Voy a corregir a `acompeltion` para ser consistente con async.

from litellm import acompletion # OVERRIDE IMPORT for async

@retry(
    stop=stop_after_attempt(2), 
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(Exception) 
)
async def _call_provider_async(model: str, messages: list, timeout: int, temperature: float = 0.7):
    return await acompletion(
        model=model,
        messages=messages,
        timeout=timeout,
        temperature=temperature
    )

from app.db import redis_client

class CircuitBreaker:
    def __init__(self):
        self.recovery_timeout = 60 # Seconds

    async def can_use_provider(self, provider: str) -> bool:
        """Verifica si el proveedor está 'sano'."""
        try:
            state = await redis_client.get(f"circuit:{provider}")
            return state != b"OPEN" # Redis returns bytes usually
        except:
            return True # Fail open if redis dies

    async def report_failure(self, provider: str):
        """Registra un fallo. Si son muchos, abre el circuito."""
        try:
            key = f"failures:{provider}"
            fails = await redis_client.incr(key)
            
            if fails > 3: # 3 fallos seguidos abre circuito
                logger.critical(f"🔥 CIRCUIT OPEN: {provider} is down. Switching to backup traffic only.")
                await redis_client.setex(f"circuit:{provider}", self.recovery_timeout, "OPEN") 
                await redis_client.delete(key) 
        except Exception as e:
            logger.error(f"CB Error: {e}")

    async def report_success(self, provider: str):
        """Si funciona, reseteamos contadores."""
        try:
            await redis_client.delete(f"failures:{provider}")
        except: 
            pass

circuit_breaker = CircuitBreaker()

async def execute_with_resilience(
    tier: str, 
    messages: List[Dict[str, str]], 
    user_id: str,
    temperature: float = 0.7
) -> Dict[str, Any]:
    """
    Ejecuta la llamada LLM con estrategias Enterprise: Circuit Breaker, Canary, Retry, Fallback.
    """
    start_time = time.time()
    
    # 0. Cargar Configuración Dinámica (DB/Redis)
    current_chains = await get_dynamic_config()
    
    # Normalizar Tier
    if tier not in current_chains:
        chain = [{"provider": "custom", "model": tier, "timeout": 30}]
    else:
        chain = current_chains[tier]

    # 1. CANARY ROUTING
    if CANARY_CONFIG["active"] and tier in CANARY_CONFIG["for_tiers"]:
        if random.random() < CANARY_CONFIG["percentage"]:
            logger.info(f"🐤 CANARY ROUTING: User {user_id} routed to {CANARY_CONFIG['target_model']}")
            try:
                response = await _call_provider_async(
                    model=CANARY_CONFIG["target_model"], 
                    messages=messages, 
                    timeout=30,
                    temperature=temperature
                )
                return response
            except Exception as e:
                logger.warning(f"Canary failed ({e}), falling back to stable chain.")

    # 2. FALLBACK CHAIN WITH IMMORTALITY (Circuit Breaker)
    last_error = None

    for attempt, node in enumerate(chain):
        provider = node['provider']
        
        # A. Chequeo de Salud (Antes de intentar)
        if not await circuit_breaker.can_use_provider(provider):
            logger.warning(f"⏩ Skipping {provider} (Circuit Open).")
            continue 

        try:
            logger.info(f"🔄 Routing Attempt {attempt+1}/{len(chain)}: {node['model']} via {node['provider']}")
            
            response = await _call_provider_async(
                model=node["model"], 
                messages=messages, 
                timeout=node["timeout"],
                temperature=temperature
            )
            
            # Éxito: Resetear fallo
            await circuit_breaker.report_success(provider)
            logger.info(f"✅ Success: {node['model']}")
            return response
            
        except Exception as e:
            # B. Aprendizaje del Fallo
            logger.error(f"❌ Failure on {provider}/{node['model']}: {str(e)}")
            last_error = e
            await circuit_breaker.report_failure(provider)
            # El bucle continúa automáticamente al siguiente proveedor

    # 3. ÚLTIMO RECURSO: EL BÚNKER (Hive Memory Fallback)
    # Si todo falla, intentamos responder con memoria colectiva
    logger.critical("☢️ ALL LIVE SYSTEMS DOWN. Engaging Offline Hive Memory.")
    try:
        from app.services.hive_memory import search_hive_mind
        # Usamos el último mensaje del usuario como query
        user_query = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), "")
        if user_query:
            fallback = await search_hive_mind(
                tenant_id="GLOBAL_EMERGENCY", # O user_id si tenemos acceso al tenant aquí
                query_text=user_query,
                limit=1
            )
            if fallback:
                 # Construimos una respuesta fake pero útil
                 logger.info("✅ Served from Hive Memory (Offline Mode)")
                 return {
                     "choices": [{"message": {"content": f"⚠️ SYSTEM OFFLINE. Served from Corporate Memory:\n\n{fallback[0]['response']}", "role": "assistant"}}],
                     "usage": {"total_tokens": 0}
                 }
    except Exception as hive_err:
        logger.error(f"Hive fallback failed: {hive_err}")

    raise ProviderError(f"Total system collapse. All providers failed. Last error: {last_error}")
