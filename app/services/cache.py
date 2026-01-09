import os
import redis
import logging

logger = logging.getLogger("agentshield.cache")
import numpy as np
from sentence_transformers import SentenceTransformer
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
        # El modelo ya debe estar en la carpeta de cache de HuggingFace gracias al Dockerfile
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model

from app.db import redis_client

async def init_semantic_cache_index():
    """Inicializa el índice vectorial en Redis"""
    try:
        schema = (
            TextField("prompt"),
            TextField("response"),
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

async def get_semantic_cache(prompt: str, threshold: float = 0.92):
    """Busca similitud semántica en Redis"""
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

async def set_semantic_cache(prompt: str, response: str):
    """Guarda el par pregunta-respuesta con su vector"""
    try:
        if not prompt or not response:
            return
            
        model = get_embedding_model()
        loop = asyncio.get_running_loop()
        vector = await loop.run_in_executor(None, lambda: model.encode(prompt).astype(np.float32).tobytes())
        key = f"cache:{hash(prompt)}"
        await redis_client.hset(key, mapping={
            "prompt": prompt,
            "response": response,
            "vector": vector
        })
        # Expiración opcional para ahorrar memoria (ej: 7 días)
        await redis_client.expire(key, 604800)
    except Exception as e:
        logger.warning(f"Cache Save Error: {e}")
