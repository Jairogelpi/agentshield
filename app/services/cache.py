import os
import redis
import logging

logger = logging.getLogger("agentshield.cache")
import numpy as np

from redis.commands.search.query import Query
from redis.commands.search.field import VectorField, TextField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType

from functools import lru_cache

# Definimos una variable global para el modelo, pero no lo cargamos aquí
_model = None

def get_embedding_model():
    """
    Carga el modelo solo bajo demanda (Lazy Loading).
    Usa el singleton para no recargar en el mismo proceso.
    """
    global _model
    if _model is None:
        logger.info("🚀 Cargando modelo de embeddings en memoria...")
        # Lazy Import to prevent startup timeout
        from sentence_transformers import SentenceTransformer
        import torch
        # SINGLE CPU TUNING: Prevent thread contention on 1-core instances
        torch.set_num_threads(1)
        
        # El modelo ya debe estar en la carpeta de cache de HuggingFace gracias al Dockerfile
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model

from app.db import redis_client
from app.models import SovereignConfig

async def init_semantic_cache_index():
    """Inicializa el índice vectorial en Redis"""
    try:
        schema = (
            TextField("prompt"),
            TextField("response"),
            TextField("tenant_id"), # Propietario del conocimiento
            TextField("share_knowledge"), # FLAG: '1' si se comparte
            VectorField("vector", "FLAT", {
                "TYPE": "FLOAT32", "DIM": 384, "DISTANCE_METRIC": "COSINE"
            })
        )
        await redis_client.ft("idx:cache").create_index(
            schema, definition=IndexDefinition(prefix=["cache:"], index_type=IndexType.HASH)
        )
        logger.info("✅ Semantic Cache Index Created.")
    except:
        pass # El índice ya existe

from app.services.reranker import verify_cache_logic
from opentelemetry import trace

async def get_sovereign_market_hit(prompt: str, current_tenant_id: str):
    """
    Busca conocimiento compartido con validación estricta 
    para evitar falsos positivos semánticos.
    """
    try:
        model = get_embedding_model()
        loop = asyncio.get_running_loop()
        vector = await loop.run_in_executor(None, lambda: model.encode(prompt).astype(np.float32).tobytes())
        
        safe_tid = current_tenant_id.replace("-", "\\-") 
        query_str = "(@share_knowledge:{1} -@tenant_id:{%s})=>[KNN 3 @vector $vec as score]" % safe_tid
        
        q = Query(query_str)\
            .return_fields("prompt", "response", "tenant_id", "score")\
            .dialect(2)
        
        res = await redis_client.ft("idx:cache").search(q, {"vec": vector})

        if res.docs:
            # Iteramos candidatos (traemos 3 por si el primero falla el Reranker)
            for hit in res.docs:
                # 1. Filtro Vectorial Rápido (First Pass)
                # Redis devuelve distancia. (1 - threshold)
                vector_score = float(hit.score)
                if vector_score > (1 - 0.90): # Si es peor que 0.90 de similitud, skip
                    continue

                # 2. VALIDACIÓN AL 100% (Cross-Encoder)
                is_valid, rerank_score = await verify_cache_logic(query=prompt, cached_query=hit.prompt)

                if is_valid: # Ya incluye check >= 0.95
                    hit_dict = {
                        "prompt": hit.prompt,
                        "response": hit.response,
                        "owner_id": hit.tenant_id,
                        "is_market_hit": True,
                        "rerank_score": rerank_score
                    }
                    return hit_dict
                else:
                     # Observabilidad
                     span = trace.get_current_span()
                     span.add_event("market_hit_rejected", {
                        "score": rerank_score,
                        "reason": "semantic_uncertainty",
                        "candidate": hit.prompt
                     })

    except Exception as e:
        logger.error(f"Sovereign Market Query Error: {e}")
    return None

async def get_semantic_cache(prompt: str, threshold: float = 0.92):
    """Busca similitud semántica en Redis (Solo Tenant Local)"""
    try:
        model = get_embedding_model()
        # CRITICAL OPTIMIZATION: Run CPU-bound embedding in threadpool to avoid blocking loop
        loop = asyncio.get_running_loop()
        vector = await loop.run_in_executor(None, lambda: model.encode(prompt).astype(np.float32).tobytes())
        # Buscamos el vecino más cercano (KNN)
        # threshold 0.92 similitud -> distance < 0.08
        q = Query("*=>[KNN 1 @vector $vec as score]")\
            .sort_by("score")\
            .return_fields("response", "score")\
            .dialect(2)
        
        res = await redis_client.ft("idx:cache").search(q, {"vec": vector})

        if res.docs:
            score = float(res.docs[0].score)
            if score < (1 - threshold): 
                return res.docs[0].response
    except Exception as e:
        logger.error(f"Cache Query Error: {e}")
    return None

async def get_semantic_cache_full_data(prompt: str, threshold: float = 0.92):
    """
    {'prompt': '...', 'response': '...'} para validación (Reranking).
    """
    try:
        model = get_embedding_model()
        loop = asyncio.get_running_loop()
        vector = await loop.run_in_executor(None, lambda: model.encode(prompt).astype(np.float32).tobytes())
        q = Query("*=>[KNN 1 @vector $vec as score]")\
            .sort_by("score")\
            .return_fields("prompt", "response", "score")\
            .dialect(2)
        
        res = await redis_client.ft("idx:cache").search(q, {"vec": vector})

        if res.docs:
            score = float(res.docs[0].score)
            if score < (1 - threshold): 
                return {
                    "prompt": res.docs[0].prompt,
                    "response": res.docs[0].response
                }
    except Exception as e:
        logger.error(f"Cache Full Query Error: {e}")
    return None

async def set_semantic_cache(prompt: str, response: str, tenant_id: str, sovereign_conf: SovereignConfig = None):
    """Guarda el par pregunta-respuesta con su vector y metadatos de soberanía"""
    try:
        if not prompt or not response:
            return
            
        model = get_embedding_model()
        loop = asyncio.get_running_loop()
        vector = await loop.run_in_executor(None, lambda: model.encode(prompt).astype(np.float32).tobytes())
        
        # Salt if user wants sovereign privacy? No, we need consistent keys for lookup?
        # Actually random hash is fine as we look up by vector.
        key = f"cache:{hash(prompt)}" 
        
        # Metadata map
        mapping = {
            "prompt": prompt,
            "response": response,
            "vector": vector,
            "tenant_id": tenant_id
        }
        
        if sovereign_conf and sovereign_conf.share_knowledge:
             mapping["share_knowledge"] = "1"
        
        await redis_client.hset(key, mapping=mapping)
        # Expiración opcional 
        await redis_client.expire(key, 604800)
    except Exception as e:
        logger.warning(f"Cache Save Error: {e}")
