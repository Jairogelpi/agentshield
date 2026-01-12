# agentshield_core/app/services/reranker.py
import asyncio
import logging
import numpy as np

logger = logging.getLogger("agentshield.reranker")

_reranker_model = None

def get_reranker_model():
    global _reranker_model
    if _reranker_model is None:
        from sentence_transformers import CrossEncoder
        import torch
        torch.set_num_threads(1)
        
        logger.info("🌍 Loading Multilingual Cross-Encoder (mMARCO)...")
        # CAMBIO CRÍTICO: Usamos mMARCO, que soporta Español, Inglés, Francés, etc.
        # Este modelo es ligero pero entiende cruce de idiomas.
        _reranker_model = CrossEncoder('cross-encoder/mmarco-mMiniLM-v2-L12-H384-v1')
    return _reranker_model

async def verify_cache_logic(query: str, cached_query: str) -> tuple[bool, float]:
    try:
        # Optimización rápida: Si son idénticos string a string, 100% match
        if query == cached_query:
            return True, 1.0

        loop = asyncio.get_running_loop()
        
        def _compute():
            model = get_reranker_model()
            # Este modelo devuelve logits (no 0-1 directo), así que aplicamos sigmoide
            # para tener un porcentaje de confianza real.
            scores = model.predict([(query, cached_query)])
            
            # Conversión Logit -> Probabilidad (Sigmoide manual simple)
            prob = 1 / (1 + np.exp(-scores[0])) 
            return float(prob)

        score = await loop.run_in_executor(None, _compute)
        
        # Ajustamos el umbral. Al cruzar idiomas, 0.85 es muy alta confianza.
        is_valid = score >= 0.85 
        
        if is_valid:
            logger.info(f"✅ Multilingual Match Approved: {score:.4f}")
        else:
            logger.info(f"🛡️ Match Rejected: {score:.4f}")
            
        return is_valid, score

    except Exception as e:
        logger.error(f"⚠️ Reranker Error: {e}")
        return False, 0.0
