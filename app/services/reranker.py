# app/services/reranker.py
import asyncio
import logging

logger = logging.getLogger("agentshield.reranker")

_reranker_model = None

def get_reranker_model():
    global _reranker_model
    if _reranker_model is None:
        from sentence_transformers import CrossEncoder
        import torch
        torch.set_num_threads(1)
        
        logger.info("⚖️ Loading Cross-Encoder (Notary-Grade)...")
        # CAMBIO CLAVE: Usamos un modelo STS que devuelve 0 a 1 nativamente
        _reranker_model = CrossEncoder('cross-encoder/stsb-distilroberta-base')
    return _reranker_model

async def verify_cache_logic(query: str, cached_query: str) -> tuple[bool, float]:
    try:
        if query == cached_query:
            return True, 1.0

        loop = asyncio.get_running_loop()
        
        def _compute():
            model = get_reranker_model()
            # Este modelo devuelve un float entre 0 y 1 directamente
            scores = model.predict([(query, cached_query)])
            return float(scores[0])

        score = await loop.run_in_executor(None, _compute)
        
        # Ahora 0.90 sí significa "90% seguro"
        is_valid = score >= 0.90 
        
        if is_valid:
            logger.info(f"✅ Reranker Approved: {score:.4f}")
        else:
            logger.info(f"🛡️ Reranker Rejected: {score:.4f}")
            
        return is_valid, score

    except Exception as e:
        logger.error(f"⚠️ Reranker Error: {e}")
        # Fail-safe: Si falla el juez, mejor no usar el caché por seguridad
        return False, 0.0
