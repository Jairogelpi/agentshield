# app/services/carbon.py
import logging
from app.db import supabase, redis_client
from app.schema import DecisionContext

logger = logging.getLogger("agentshield.carbon")

# Intensidad de Carbono (gCO2/kWh) aproximada por proveedor/región
GRID_INTENSITY = {
    "azure-eu": 250,   # Irlanda/Holanda (Promedio)
    "openai-us": 400,  # US Grid Avg
    "anthropic": 200   # AWS Low Carbon regions
}

# Consumo estimado (kWh per 1k tokens) - Aproximación Enterprise
ENERGY_PER_1K_TOKENS = {
    "gpt-4": 0.004,
    "gpt-3.5-turbo": 0.0004, # 10x más eficiente
    "agentshield-eco": 0.0003
}

class CarbonGovernor:
    def estimate_footprint(self, model: str, prompt_tokens: int, output_tokens: int = 0) -> float:
        """Calcula gramos de CO2 previstos."""
        # Normalizar nombre del modelo
        model_name = str(model).lower()
        model_key = "gpt-4" if "gpt-4" in model_name else "gpt-3.5-turbo"
        energy_factor = ENERGY_PER_1K_TOKENS.get(model_key, 0.001)
        
        total_tokens = prompt_tokens + output_tokens
        kwh = (total_tokens / 1000) * energy_factor
        
        # Asumimos región US por defecto si no sabemos
        grams_co2 = kwh * GRID_INTENSITY["openai-us"]
        return grams_co2

    async def check_budget_and_route(self, ctx: DecisionContext) -> DecisionContext:
        """
        El 'Carbon Gate'.
        1. Estima CO2.
        2. Verifica presupuesto del depto.
        3. Si Intención es simple y Modelo es pesado -> GREEN ROUTING.
        """
        # A. Estimación Pre-Flight (Asumimos output = input para estimar)
        estimated_g = self.estimate_footprint(ctx.requested_model, 1000) # Placeholder 1k tokens
        ctx.co2_estimated = estimated_g
        
        # B. Green Routing (La lógica de impacto)
        # Si pide GPT-4 para decir "Hola" -> Bajar a Eco
        green_intents = ["GREETING", "CHIT_CHAT", "SUMMARIZATION_SIMPLE"]
        is_heavy_model = any(x in ctx.requested_model.lower() for x in ["gpt-4", "opus", "sonnet"])
        
        if ctx.intent in green_intents and is_heavy_model:
            ctx.effective_model = "agentshield-eco" # Downgrade inteligente
            ctx.green_routing_active = True
            ctx.log("CARBON", f"Green Routing Activated: {ctx.requested_model} -> agentshield-eco")
            return ctx

        # C. Chequeo de Presupuesto (Solo si no hubo routing)
        if ctx.dept_id:
            # Leer caché de presupuesto (Redis) para velocidad
            key = f"budget:co2:{ctx.dept_id}"
            current_spend = await redis_client.get(key)
            
            # Si se llena, evita OOM.
            if current_spend and float(current_spend) > 5000: # Límite hardcodeado de ejemplo (5kg)
                # Opciones: Bloquear o Downgrade forzoso
                ctx.effective_model = "agentshield-eco"
                ctx.log("CARBON", "Monthly Carbon Budget Exceeded. Forcing Eco Mode.")
        
        return ctx

    async def log_emission(self, tenant_id, dept_id, user_id, trace_id, model, grams):
        """Registra la emisión real en el Ledger (Background Task)"""
        try:
            supabase.table("carbon_ledger").insert({
                "tenant_id": tenant_id,
                "department_id": dept_id,
                "user_id": user_id,
                "trace_id": trace_id,
                "model_used": model,
                "grams_co2": grams
            }).execute()
            
            # Actualizar acumulado en Redis para el Gate
            if dept_id:
                await redis_client.incrbyfloat(f"budget:co2:{dept_id}", grams)
                
        except Exception as e:
            logger.error(f"Failed to log carbon: {e}")

carbon_governor = CarbonGovernor()
