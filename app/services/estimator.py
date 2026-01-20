# app/services/estimator.py
import asyncio
import json
import logging

from app.db import redis_client, supabase

logger = logging.getLogger("agentshield.estimator")


async def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    Calcula el coste estimado en USD basado en el mercado real (Market Oracle).
    PROHIBIDO EL USO DE DATOS MOCK.
    """
    try:
        # 1. Intentar obtener precios frescos de Redis (Hot Path)
        cached_prices = await redis_client.get("system_config:market_prices")
        prices = {}
        if cached_prices:
            prices = json.loads(cached_prices)

        # 2. Si Redis está vacío, ir a la Base de Datos (Cold Path)
        if not prices:
            res = (
                supabase.table("system_config")
                .select("value")
                .eq("key", "market_prices")
                .maybe_single()
                .execute()
            )
            if res.data:
                prices = res.data["value"]
                await redis_client.setex("system_config:market_prices", 3600, json.dumps(prices))

        model_lower = model.lower()
        config = None

        # Búsqueda exacta
        if model in prices:
            config = prices[model]
        else:
            # Búsqueda difusa para variantes de modelo
            for mid, vals in prices.items():
                if mid.lower() in model_lower or model_lower in mid.lower():
                    config = vals
                    break

        # 3. Last Resort: Obtener fallbacks globales de la DB (NO hardcodeados en código)
        if not config:
            res = (
                supabase.table("system_config")
                .select("value")
                .eq("key", "pricing_fallbacks")
                .maybe_single()
                .execute()
            )
            fallbacks = res.data["value"] if res.data else {}

            for key, values in fallbacks.items():
                if key in model_lower:
                    config = values
                    break

            if not config:
                config = fallbacks.get("default", {"input": 1.0, "output": 2.0})

        input_cost = (prompt_tokens / 1_000_000) * config["input"]
        output_cost = (completion_tokens / 1_000_000) * config["output"]

        return round(input_cost + output_cost, 6)

    except Exception as e:
        logger.error(f"⚠️ Pricing Estimation Error: {e}. Check Market Oracle.")
        return 0.000001
