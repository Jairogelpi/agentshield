# app/services/config_manager.py
import asyncio
import json
import logging
from typing import Any, Dict, Optional

from app.db import redis_client, supabase

logger = logging.getLogger("agentshield.config")


class ConfigManager:
    """
    Gestor de configuración dinámica de AgentShield.
    Cae en cascada: Redis (Hot) -> DB (Cold) -> Hardcoded Fallback (Last Resort).
    """

    @staticmethod
    async def get_val(key: str, default: Any = None) -> Any:
        """Obtiene un valor de configuración de forma asíncrona."""
        redis_key = f"system_config:{key}"

        # 1. TIER 0: REDIS
        try:
            cached = await redis_client.get(redis_key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Redis config fetch failed for {key}: {e}")

        # 2. TIER 1: SUPABASE
        try:
            loop = asyncio.get_running_loop()

            def _fetch():
                return (
                    supabase.table("system_config")
                    .select("value")
                    .eq("key", key)
                    .maybe_single()
                    .execute()
                )

            res = await loop.run_in_executor(None, _fetch)
            if res.data:
                val = res.data["value"]
                # Re-hidratar Redis (TTL 10 mins)
                await redis_client.setex(redis_key, 600, json.dumps(val))
                return val
        except Exception as e:
            logger.error(f"DB config fetch failed for {key}: {e}")

        return default

    async def get_carbon_intensity(self) -> dict[str, float]:
        return await self.get_val(
            "carbon_grid_intensity",
            {"azure-eu": 250, "openai-us": 400, "anthropic": 200, "default": 350},
        )

    async def get_energy_factors(self) -> dict[str, float]:
        return await self.get_val(
            "energy_per_1k_tokens",
            {"gpt-4": 0.004, "gpt-4o": 0.002, "gpt-3.5-turbo": 0.0004, "default": 0.001},
        )

    async def get_pricing_fallbacks(self) -> dict[str, dict[str, float]]:
        return await self.get_val(
            "pricing_fallbacks",
            {
                "gpt-4": {"input": 30.0, "output": 60.0},
                "gpt-4o": {"input": 5.0, "output": 15.0},
                "default": {"input": 1.0, "output": 2.0},
            },
        )

    async def get_governance_defaults(self) -> dict[str, Any]:
        return await self.get_val(
            "governance_defaults",
            {"default_cost_center_name": "GENERIC-CC", "co2_soft_limit_g": 5000},
        )


config_manager = ConfigManager()
