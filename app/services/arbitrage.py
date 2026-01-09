# agentshield_core/app/services/arbitrage.py
from app.utils import fast_json as json
import logging
from litellm import acompletion
from app.db import redis_client, supabase

logger = logging.getLogger("agentshield.arbitrage")

class WiseArbitrageEngine:
    def __init__(self):
        self.router_model = "groq/llama3-8b-8192"
        # SLA: 2000ms. Si predicimos más que esto, penalizamos.
        self.latency_threshold_ms = 2000 
        
        # --- KALMAN FILTER (LUA SCRIPT 2026) ---
        # State-Space Model para latencia de red.
        # x = Estimación del estado (Latencia)
        # p = Covarianza del error (Incertidumbre)
        # q = Ruido del proceso (Qué tan volátil es el proveedor por naturaleza) ~ 0.1
        # r = Ruido de la medición (Jitter de la red) ~ 10.0
        self.kalman_script = redis_client.register_script("""
            local key_x = KEYS[1] -- Estado (Latencia Estimada)
            local key_p = KEYS[2] -- Incertidumbre (Covarianza)
            
            local measurement = tonumber(ARGV[1])
            local Q = 0.05  -- Process Noise (Asumimos estabilidad inherente)
            local R = 50.0  -- Measurement Noise (Jitter de Internet alto)
            
            -- 1. Recuperar estado previo
            local x = tonumber(redis.call('GET', key_x)) or measurement
            local p = tonumber(redis.call('GET', key_p)) or 1.0
            
            -- 2. PREDICT (Proyección a priori)
            -- Asumimos modelo estático x(k) = x(k-1) para latencia base
            local x_pred = x
            local p_pred = p + Q
            
            -- 3. UPDATE (Corrección basada en medición)
            -- Ganancia de Kalman (K): Cuánto confiamos en el nuevo dato vs historia
            local K = p_pred / (p_pred + R)
            
            -- Actualizar estado
            local x_new = x_pred + K * (measurement - x_pred)
            local p_new = (1 - K) * p_pred
            
            -- Guardar
            redis.call('SET', key_x, x_new)
            redis.call('SET', key_p, p_new)
            
            -- Retornar: [Latencia Estimada, Incertidumbre/Riesgo]
            return {x_new, p_new}
        """) 

    async def _get_arbitrage_rules(self) -> dict:
        """Carga reglas dinámicas (Cache + DB)"""
        CACHE_KEY = "system_config:arbitrage_rules"
        cached = await redis_client.get(CACHE_KEY)
        if cached: return json.loads(cached)
            
        try:
            res = supabase.table("system_config").select("value").eq("key", "arbitrage_rules").single().execute()
            if res.data:
                rules = res.data['value']
                await redis_client.setex(CACHE_KEY, 300, json.dumps(rules))
                return rules
        except: pass
        
        return {
            "thresholds": {"trivial_score": 30, "standard_score": 70},
            "pricing": {"trivial_max_price": 0.5, "standard_max_price": 5.0}
        }

    async def _get_market_models(self):
        cached = await redis_client.get("market:active_models_v2")
        if cached: return json.loads(cached)
        res = supabase.table("model_prices").select("*").eq("is_active", True).execute()
        models = res.data
        await redis_client.setex("market:active_models_v2", 600, json.dumps(models))
        return models

    async def get_model_metrics(self, model: str) -> tuple[float, float]:
        """
        Devuelve (Latencia Estimada, Incertidumbre).
        La incertidumbre (P) nos dice si el proveedor es errático.
        """
        x = await redis_client.get(f"stats:latency:{model}:x")
        p = await redis_client.get(f"stats:latency:{model}:p")
        return float(x) if x else 500.0, float(p) if p else 1.0

    async def record_latency(self, model: str, ms: float):
        """
        Ingesta datos en el Filtro de Kalman.
        Operación atómica en Redis (High-Frequency safe).
        """
        try:
            # Keys separadas para Estado (x) e Incertidumbre (p)
            key_x = f"stats:latency:{model}:x"
            key_p = f"stats:latency:{model}:p"
            await self.kalman_script(keys=[key_x, key_p], args=[ms])
        except Exception as e:
            logger.warning(f"Kalman update failed: {e}")

    async def analyze_complexity(self, messages: list) -> dict:
        """Juez IA (Sin cambios, ya es eficiente)"""
        user_content = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), "")
        est_tokens = len(user_content) // 4
        
        system_prompt = (
            "Analyze prompt complexity. Return JSON:\n"
            "- score (0-100): 0=trivial, 100=complex.\n"
            f"Prompt: {user_content[:500]}"
        )
        try:
            res = await acompletion(
                model=self.router_model, 
                messages=[{"role": "system", "content": system_prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(res.choices[0].message.content)
            data['input_tokens'] = est_tokens
            return data
        except:
            return {"score": 100, "input_tokens": est_tokens}

    async def find_best_bidder(self, requested_model: str, analysis: dict, max_output_tokens: int = 1000, tenant_allowlist: list = None):
        """
        Subasta Cuántica 2026: Precio + Contexto + Kalman Prediction + Reglas de Mercado.
        """
        rules = await self._get_arbitrage_rules()
        PRICE_MAX_TRIVIAL = rules.get("pricing", {}).get("trivial_max_price", 0.5)
        PRICE_MAX_STD = rules.get("pricing", {}).get("standard_max_price", 5.0)
        
        score = analysis.get("score", 100)
        input_tokens = analysis.get("input_tokens", 0)
        
        # 1. Seguridad Cognitiva
        th_std = rules.get("thresholds", {}).get("standard_score", 70)
        if score > th_std:
            return requested_model, "COMPLEXITY_RETAINED", 0.0

        market_models = await self._get_market_models()
        target = next((m for m in market_models if m['model'] == requested_model), None)
        target_price = float(target['price_out']) if target else 100.0
        
        candidates = []
        for m in market_models:
            m_id = m['model']
            price = float(m.get('price_out', 0) or 0)
            context = int(m.get('context_window', 4096))
            
            # Filtros duros
            if tenant_allowlist and m_id not in tenant_allowlist: continue
            if context < (input_tokens + max_output_tokens): continue

            # --- FILTRO PREDICTIVO (KALMAN) ---
            # Obtenemos Latencia Estimada (x) y Volatilidad (p)
            lat_est, volatility = await self.get_model_metrics(m_id)
            
            # Penalización por Riesgo:
            # "Coste Efectivo de Latencia" = Latencia + (Volatilidad * 100)
            # Si un modelo es rápido (200ms) pero muy incierto (p=5.0), lo tratamos como de 700ms.
            risk_adjusted_latency = lat_est + (volatility * 100)
            
            if risk_adjusted_latency > self.latency_threshold_ms:
                continue

            # Filtros de Precio Dinámicos (Oracle)
            th_triv = rules["thresholds"]["trivial_score"]
            
            if score < th_triv: 
                if price <= PRICE_MAX_TRIVIAL and price < target_price: 
                    candidates.append(m)
            elif score <= th_std:
                if price <= PRICE_MAX_STD and price < target_price:
                    candidates.append(m)
        
        if not candidates:
            return requested_model, "NO_BETTER_OPTION", 0.0

        # Selección: Minimizamos precio, pero podríamos minimizar (Precio * Latencia)
        winner = min(candidates, key=lambda x: float(x.get('price_out', 0)))
        winner_id = winner['model']
        
        savings = (target_price - float(winner.get('price_out', 0))) / target_price if target_price > 0 else 0
        return winner_id, "SMART_ROUTING", savings

arbitrage_engine = WiseArbitrageEngine()
