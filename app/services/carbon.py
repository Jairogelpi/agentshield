# app/services/carbon.py
import asyncio
import json
import logging

from app.db import redis_client, supabase
from app.schema import DecisionContext
from app.services.carbon_oracle import fetch_real_carbon_intensity

logger = logging.getLogger("agentshield.carbon")


class CarbonGovernor:
    async def get_dynamic_config(self) -> dict:
        """Obtiene factores de energía y límites de la DB/Redis."""
        try:
            cached = await redis_client.get("system_config:energy_per_1k_tokens")
            if cached:
                return json.loads(cached)

            res = (
                supabase.table("system_config")
                .select("value")
                .eq("key", "energy_per_1k_tokens")
                .maybe_single()
                .execute()
            )
            if res.data:
                val = res.data["value"]
                await redis_client.setex(
                    "system_config:energy_per_1k_tokens", 3600, json.dumps(val)
                )
                return val
        except:
            pass
        return {"default": 0.001}

    async def estimate_footprint(
        self, model: str, prompt_tokens: int, output_tokens: int = 0
    ) -> float:
        """Calcula gramos de CO2 usando intensidad en tiempo real."""
        model_name = str(model).lower()
        energy_config = await self.get_dynamic_config()

        # Buscar factor de energía
        energy_factor = energy_config.get("default", 0.001)
        for key, val in energy_config.items():
            if key in model_name:
                energy_factor = val
                break

        total_tokens = prompt_tokens + output_tokens
        kwh = (total_tokens / 1000) * energy_factor

        # INTENSIDAD REAL de Carbon Oracle (API Pública)
        intensity = await fetch_real_carbon_intensity()

        grams_co2 = kwh * intensity
        return grams_co2

    async def check_budget_and_route(self, ctx: DecisionContext) -> DecisionContext:
        """
        El 'Carbon Gate' con datos en tiempo real.
        """
        # A. Estimación Real Pre-Flight
        intensity = await fetch_real_carbon_intensity()
        ctx.co2_estimated = await self.estimate_footprint(ctx.requested_model, 1000)

        # B. Green Routing
        green_intents = ["GREETING", "CHIT_CHAT", "SUMMARIZATION_SIMPLE", "COPYWRITING_SIMPLE"]
        is_heavy_model = any(x in ctx.requested_model.lower() for x in ["gpt-4", "opus", "sonnet"])

        if ctx.intent in green_intents and is_heavy_model:
            ctx.effective_model = "agentshield-eco"
            ctx.green_routing_active = True
            ctx.log(
                "CARBON", f"Green Routing LIVE: Intensity is {intensity} gCO2/kWh. Routed to Eco."
            )
            return ctx

        # C. Chequeo de Presupuesto Real (desde Tabla departments)
        if ctx.dept_id:
            res = (
                supabase.table("departments")
                .select("co2_monthly_limit_grams, current_co2_spend_grams")
                .eq("id", ctx.dept_id)
                .maybe_single()
                .execute()
            )
            if res.data:
                limit = float(res.data.get("co2_monthly_limit_grams", 5000))
                current = float(res.data.get("current_co2_spend_grams", 0))

                if current > limit:
                    if not ctx.green_routing_active:
                        ctx.effective_model = "agentshield-eco"
                        ctx.log(
                            "CARBON",
                            f"DEPT BUDGET EXCEEDED ({current}/{limit}g). Forcing Eco Mode.",
                        )

        return ctx

    async def log_emission(
        self, tenant_id, dept_id, user_id, trace_id, model, grams, avoided_grams=0.0
    ):
        """Registra la emisión real y actualiza el contador del departamento."""
        try:
            supabase.table("carbon_ledger").insert(
                {
                    "tenant_id": tenant_id,
                    "department_id": dept_id,
                    "user_id": user_id,
                    "trace_id": trace_id,
                    "model_used": model,
                    "grams_co2": grams,
                    "co2_avoided": avoided_grams,
                }
            ).execute()

            # Actualización Directa en la Tabla de Departamentos (Atomic RPC)
            if dept_id:
                supabase.rpc(
                    "increment_dept_carbon", {"p_dept_id": dept_id, "p_grams": grams}
                ).execute()

        except Exception as e:
            logger.error(f"Failed to log carbon: {e}")


carbon_governor = CarbonGovernor()
