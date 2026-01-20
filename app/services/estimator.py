# app/services/estimator.py
import logging

logger = logging.getLogger("agentshield.estimator")

# Static Pricing Table (Price per 1M tokens) - Fallback
# In a real scenario, this would come from market_oracle or a DB config
PRICING_TABLE = {
    "gpt-4": {"input": 30.0, "output": 60.0},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "gpt-4o": {"input": 5.0, "output": 15.0},
    "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
    "claude-3-opus": {"input": 15.0, "output": 75.0},
    "claude-3-sonnet": {"input": 3.0, "output": 15.0},
    "agentshield-fast": {"input": 0.2, "output": 0.6},
    "agentshield-eco": {"input": 0.1, "output": 0.3},
    "agentshield-secure": {"input": 1.0, "output": 2.0},
    "default": {"input": 1.0, "output": 2.0}
}

from app.db import redis_client
import json
import asyncio

async def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    Calcula el coste estimado en USD basado en el mercado real.
    Busca en el caché de Market Oracle (Redis).
    """
    try:
        # 1. Intentar obtener precios de Redis
        cached_prices = await redis_client.get("system_config:market_prices")
        prices = {}
        if cached_prices:
            prices = json.loads(cached_prices)
        
        # 2. Buscar el modelo
        model_lower = model.lower()
        config = None
        
        # Búsqueda exacta primero
        if model in prices:
            config = prices[model]
        else:
            # Búsqueda por similitud
            for mid, vals in prices.items():
                if mid.lower() in model_lower or model_lower in mid.lower():
                    config = vals
                    break
        
        # 3. Fallback al PRICING_TABLE estático si falla el oráculo
        if not config:
            for key, values in PRICING_TABLE.items():
                if key in model_lower:
                    config = values
                    break
        
        if not config:
            config = PRICING_TABLE["default"]

        input_cost = (prompt_tokens / 1_000_000) * config["input"]
        output_cost = (completion_tokens / 1_000_000) * config["output"]
        
        return round(input_cost + output_cost, 6)
    except Exception as e:
        logger.error(f"Error en estimación dinámica: {e}")
        # Fallback ultra-seguro
        return 0.000001
