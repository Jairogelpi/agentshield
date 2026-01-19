import os
import redis
import logging
import json
import asyncio
import numpy as np

from redis.commands.search.query import Query
from redis.commands.search.field import VectorField, TextField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from litellm import embedding
from opentelemetry import trace

logger = logging.getLogger("agentshield.cache")

# Constants
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
VECTOR_DIM = 1536  # text-embedding-3-small has 1536 dimensions

from app.db import redis_client
from app.models import SovereignConfig

async def get_embedding(text: str) -> bytes:
    """
    Generates embedding using LiteLLM (OpenAI compatible).
    Returns raw bytes for Redis Vector Search (FLOAT32).
    """
    try:
        loop = asyncio.get_running_loop()
        # Run I/O bound API call in thread to avoid blocking loop
        response = await loop.run_in_executor(
            None, 
            lambda: embedding(model=EMBEDDING_MODEL, input=[text])
        )
        vector = response['data'][0]['embedding']
        return np.array(vector, dtype=np.float32).tobytes()
    except Exception as e:
        logger.error(f"Embedding Generation Error: {e}")
        raise e

async def init_semantic_cache_index():
    """Inicializa el índice vectorial en Redis con dimensiones para text-embedding-3-small"""
    try:
        # Check if index exists to hopefully avoid error log
        try:
            await redis_client.ft("idx:cache").info()
            return # Index exists
        except:
            pass # Index does not exist, create it

        schema = (
            TextField("prompt"),
            TextField("response"),
            TextField("tenant_id"), # Propietario del conocimiento
            TextField("share_knowledge"), # FLAG: '1' si se comparte
            VectorField("vector", "FLAT", {
                "TYPE": "FLOAT32", "DIM": VECTOR_DIM, "DISTANCE_METRIC": "COSINE"
            })
        )
        await redis_client.ft("idx:cache").create_index(
            schema, definition=IndexDefinition(prefix=["cache:"], index_type=IndexType.HASH)
        )
        logger.info(f"✅ Semantic Cache Index Created (Dim: {VECTOR_DIM}).")
    except Exception as e:
        logger.warning(f"Semantic Cache Index Init Warning: {e}")

# app/services/cache.py
import hashlib
import json
from app.db import redis_client
import logging

logger = logging.getLogger("agentshield.cache")

# --- SMART CACHING (NORMALIZED HASH) ---
async def get_smart_cache_key(messages: list, model_tier: str, tenant_id: str) -> str:
    """
    Genera una clave de caché inteligente.
    Ignora mayúsculas, espacios extra y puntuación para aumentar el 'Cache Hit Rate'.
    """
    if not messages: return None
    
    # Solo cacheamos el último mensaje del usuario para RAG simple o Q&A
    last_msg = messages[-1].get('content', '')
    if not isinstance(last_msg, str): return None
    
    # Normalización (Enterprise trick)
    normalized_content = "".join(e for e in last_msg if e.isalnum()).lower()
    
    # Hash seguro
    content_hash = hashlib.sha256(normalized_content.encode()).hexdigest()
    
    # La clave incluye el tenant (para no filtrar datos entre empresas) y el modelo
    return f"cache:{tenant_id}:{model_tier}:{content_hash}"

async def check_cache(messages: list, model_tier: str, tenant_id: str):
    key = await get_smart_cache_key(messages, model_tier, tenant_id)
    if not key: return None
    
    try:
        cached_raw = await redis_client.get(key)
        if cached_raw:
            return json.loads(cached_raw)
    except Exception as e:
        logger.warning(f"Cache get failed: {e}")
    return None

async def set_cache(messages: list, model_tier: str, tenant_id: str, response: dict):
    """
    Guarda en caché con TTL dinámico.
    Respuestas complejas (Smart) viven más tiempo que las rápidas (Fast).
    """
    key = await get_smart_cache_key(messages, model_tier, tenant_id)
    if not key: return

    # TTL Dinámico
    ttl = 3600 # 1 hora default
    if "smart" in model_tier:
        ttl = 86400 # 24 horas para GPT-4 (es caro, vale la pena guardar)
    
    try:
        # response might be a Pydantic model from litellm, need ensuring it is dict/json serializable
        # If it is a Pydantic model (ModelResponse), .json() or .dict() works.
        # But set_cache might receive a dict from proxy.
        if hasattr(response, 'json') and callable(response.json):
             val = response.json()
        elif hasattr(response, 'dict') and callable(response.dict):
             val = json.dumps(response.dict())
        else:
             val = json.dumps(response)
             
        await redis_client.setex(key, ttl, val)
    except Exception as e:
        logger.warning(f"Cache set failed: {e}")

# --- LEGACY / SEMANTIC EXPORTS (Keeping placeholders if needed by other files) ---
async def get_semantic_cache(*args, **kwargs):
    # Placeholder to prevent import errors if proxy.py still references it before full update
    pass

async def set_semantic_cache(*args, **kwargs):
    pass
from app.services.reranker import verify_cache_logic

async def get_semantic_cache(prompt: str, threshold: float = 0.90, tenant_id: str = "*"):
    """
    Estrategia en Cascada (Waterfall):
    1. Tier 0: Match Exacto (Hash) -> 0ms latencia, $0 costo.
    2. Tier 1: Búsqueda Vectorial (Redis) -> 10ms latencia.
    3. Tier 2: Verificación (Reranker) -> Asegura que no sea un falso positivo.
    """
    try:
        # --- TIER 0: Hash Exacto (Velocidad Luz) ---
        # Si el prompt es idéntico letra por letra, no generes embeddings.
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        exact_key = f"cache:exact:{tenant_id}:{prompt_hash}"
        exact_hit = await redis_client.get(exact_key)
        
        if exact_hit:
            logger.info("⚡ CACHE HIT (EXACT MATCH) - Ahorro total de latencia.")
            return json.loads(exact_hit)['response']

        # --- TIER 1: Embedding + Vector Search ---
        # Solo si no es exacto, pagamos el coste del embedding
        vector = await get_embedding(prompt)
        
        # Simplificación: Buscamos globalmente o por tenant. 
        base_query = "*=>[KNN 3 @vector $vec as score]" # Traemos 3 candidatos
        
        q = Query(base_query)\
            .sort_by("score")\
            .return_fields("response", "score", "tenant_id", "prompt")\
            .dialect(2)
        
        res = await redis_client.ft("idx:cache").search(q, {"vec": vector})

        if res.docs:
            candidate = res.docs[0]
            score = float(candidate.score)
            
            # Redis Distance (Cosine) = 1 - Similarity
            required_distance = 1 - threshold 
            
            if score < required_distance:
                # Privacy Check (Optional: enforce tenant isolation)
                if tenant_id != "*" and getattr(candidate, 'tenant_id', '') != tenant_id:
                     return None

                # --- TIER 2: El Notario (Reranker) ---
                # Validamos que la respuesta sirva realmente
                cached_prompt = getattr(candidate, 'prompt', '')
                is_valid, rerank_score = await verify_cache_logic(prompt, cached_prompt)
                
                if is_valid:
                    logger.info(f"✅ Semantic Match Validated by Reranker: {rerank_score:.4f}")
                    return candidate.response
                else:
                    logger.warning(f"🛡️ Vector Match rejected by Reranker (Score: {rerank_score})")
                    return None
                    
    except Exception as e:
        logger.error(f"Cache Query Error: {e}")
    return None

async def set_semantic_cache(prompt: str, response: str, tenant_id: str):
    """Guarda tanto el Hash Exacto como el Vector"""
    try:
        if not prompt or not response:
            return

        # 1. Guardar Hash Exacto (Para el Tier 0)
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        exact_key = f"cache:exact:{tenant_id}:{prompt_hash}"
        exact_data = {"response": response}
        await redis_client.setex(exact_key, 604800, json.dumps(exact_data))
            
        # 2. Guardar Vector (Para el Tier 1)
        vector = await get_embedding(prompt)
        
        cache_key = f"cache:{prompt_hash}" 
        
        mapping = {
            "prompt": prompt,
            "response": response,
            "tenant_id": tenant_id,
            "vector": vector
        }
        
        await redis_client.hset(cache_key, mapping=mapping)
        await redis_client.expire(cache_key, 604800) # 7 días de TTL
        
    except Exception as e:
        logger.warning(f"Cache Save Error: {e}")

