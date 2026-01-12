import logging
import asyncio
from flashrank import Ranker, RerankRequest

# Configuración del Logger existente
logger = logging.getLogger("agentshield.reranker")

_reranker = None

def get_reranker_model():
    """
    Carga el modelo ONNX cuantizado en memoria (Singleton).
    FlashRank descarga el modelo (~20MB) automáticamente en la primera ejecución
    y lo guarda en cache_dir.
    """
    global _reranker
    if _reranker is None:
        logger.info("⚡ Loading Nano-Reranker (ONNX Quantized)...")
        # ms-marco-MiniLM-L-12-v2 es el estándar "Gold" de eficiencia/precisión
        _reranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/opt/models")
    return _reranker

async def verify_cache_logic(query: str, cached_query: str) -> tuple[bool, float]:
    """
    Valida si el 'query' actual significa lo mismo que el 'cached_query'.
    Usa ONNX Runtime para una inferencia ultra-rápida (<30ms).
    """
    try:
        # 1. Optimización Trivial: Match Exacto (String puro)
        if query == cached_query:
            return True, 1.0

        # NOTA: No usamos RapidFuzz aquí para no perder detección de sinónimos.
        
        # 2. Reranking Ultra-Rápido (ONNX)
        # Ejecutamos en un executor para no bloquear el Event Loop principal,
        # aunque FlashRank es tan rápido que el bloqueo es mínimo.
        loop = asyncio.get_running_loop()
        
        def _run_inference():
            ranker = get_reranker_model()
            request = RerankRequest(query=query, passages=[{"text": cached_query}])
            return ranker.rerank(request)

        # Offload a hilo para mantener la naturaleza "Non-blocking" de AgentShield
        results = await loop.run_in_executor(None, _run_inference)
        
        if not results:
            return False, 0.0
            
        score = results[0]['score'] # FlashRank devuelve score de 0.0 a 1.0 aprox
        
        # Ajuste de umbral: 0.85 suele ser muy seguro para cross-encoder
        is_valid = score >= 0.85
        
        if is_valid:
            logger.info(f"✅ Semantic Match (ONNX): {score:.4f}")
        else:
            logger.info(f"🛡️ Match Rejected: {score:.4f}")
            
        return is_valid, score

    except Exception as e:
        logger.error(f"⚠️ Reranker Error: {e}")
        # Fail-safe: Si falla el reranker, asumimos que NO es match para evitar devolver basura.
        return False, 0.0
