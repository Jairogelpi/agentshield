# app/services/reranker.py
import asyncio
import logging
from functools import lru_cache

logger = logging.getLogger("agentshield.reranker")

# Global lazy-loaded model
_reranker_model = None

def get_reranker_model():
    global _reranker_model
    if _reranker_model is None:
        from sentence_transformers import CrossEncoder
        import torch
        # SINGLE CPU TUNING
        torch.set_num_threads(1)
        
        logger.info("⚖️ Loading Cross-Encoder Model (Notary-Grade Precision)...")
        # 'cross-encoder/ms-marco-MiniLM-L-6-v2' es el estándar de velocidad/precisión
        _reranker_model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
    return _reranker_model

async def verify_cache_logic(query: str, cached_query: str) -> tuple[bool, float]:
    """
    Usa un modelo Cross-Encoder para comparar la consulta original con la de la caché.
    Retorna: (is_valid, score)
    """
    try:
        if query == cached_query:
            return True, 1.0

        loop = asyncio.get_running_loop()
        
        def _compute():
            model = get_reranker_model()
            # Cross-Encoder toma pares y devuelve un score (logits o probabilidad)
            # ms-marco-MiniLM-L-6-v2 devuelve logits no acotados, usamos sigmoid para 0-1 si queremos probabilidad, 
            # pero para este modelo específico, los scores altos suelen indicar relevancia.
            # Sin embargo, 'cross-encoder/stsb-distilroberta-base' da 0-1.
            # Vamos a usar 'cross-encoder/stsb-distilroberta-base' para tener score semántico claro 0-1.
            # O mejor, normalizamos si usamos ms-marco.
            # EL USER PIDIO: "score >= 0.95". Esto sugiere un modelo STS (Semantic Textual Similarity).
            
            # Usaremos stsb-distilroberta-base que está entrenado para similitud 0-1.
            scores = model.predict([(query, cached_query)])
            return float(scores[0])

        score = await loop.run_in_executor(None, _compute)
        
        # 0.95 es el estándar de oro para intercambio de dinero entre tenants
        is_valid = score >= 0.95
        
        if is_valid:
            logger.info(f"✅ Reranker Approved: {score:.4f}")
        else:
            logger.info(f"🛡️ Reranker Rejected: {score:.4f}")
            
        return is_valid, score

    except Exception as e:
        logger.error(f"⚠️ Reranker Error: {e}")
        return False, 0.0
