# agentshield_core/app/services/arbitrage.py
import json
import logging
from litellm import acompletion
from app.db import redis_client, supabase

logger = logging.getLogger("agentshield.arbitrage")

class WiseArbitrageEngine:
    def __init__(self):
        self.router_model = "groq/llama3-8b-8192" 
        # Penalización: Si la latencia > 2000ms, consideramos el modelo "saturado"
        self.latency_threshold_ms = 2000 
        
    async def _get_market_models(self):
        """Recupera modelos y sus capacidades (precio + context window)"""
        cached = redis_client.get("market:active_models_v2")
        if cached: return json.loads(cached)
            
        res = supabase.table("model_prices").select("*").eq("is_active", True).execute()
        models = res.data
        redis_client.setex("market:active_models_v2", 600, json.dumps(models))
        return models

    async def get_model_latency(self, model: str) -> float:
        """Obtiene la latencia promedio reciente (EMA) desde Redis"""
        # Si no hay datos, asumimos una latencia sana por defecto (500ms)
        l = redis_client.get(f"stats:latency:{model}")
        return float(l) if l else 500.0

    async def record_latency(self, model: str, ms: float):
        """
        Aprendizaje en Tiempo Real:
        Actualiza el promedio móvil de latencia.
        Fórmula EMA: NewAvg = (OldAvg * 0.8) + (NewVal * 0.2)
        Esto hace que el sistema reaccione rápido a picos de lag.
        """
        key = f"stats:latency:{model}"
        old_val = redis_client.get(key)
        
        if old_val:
            new_avg = (float(old_val) * 0.8) + (ms * 0.2)
        else:
            new_avg = ms
            
        redis_client.set(key, new_avg)

    async def analyze_complexity(self, messages: list) -> dict:
        """El Juez IA: Determina dificultad y cuenta tokens aproximados"""
        user_content = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), "")
        # Estimación rápida de tokens (caracteres / 4) para el filtro de contexto
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

    async def find_best_bidder(self, requested_model: str, analysis: dict):
        """
        Subasta Inteligente: Precio + Contexto + Latencia (SLA)
        """
        score = analysis.get("score", 100)
        input_tokens = analysis.get("input_tokens", 0)
        
        # 1. Seguridad Cognitiva: Si es complejo, no degradamos.
        if score > 70:
            return requested_model, "COMPLEXITY_RETAINED", 0.0

        market_models = await self._get_market_models()
        
        # Benchmark (modelo solicitado)
        target = next((m for m in market_models if m['model'] == requested_model), None)
        target_price = float(target['price_out']) if target else 100.0
        
        candidates = []
        for m in market_models:
            m_id = m['model']
            price = float(m.get('price_out', 0) or 0)
            context = int(m.get('context_window', 4096))
            
            # FILTRO 1: Context Window (Físicamente posible)
            # Necesitamos espacio para input + output. Asumimos output modesto (1k)
            if context < (input_tokens + 1000):
                continue

            # FILTRO 2: Latencia (Calidad de Servicio - SLA)
            current_lag = await self.get_model_latency(m_id)
            if current_lag > self.latency_threshold_ms:
                # El modelo está saturado o es lento. Lo descartamos aunque sea barato.
                continue

            # FILTRO 3: Reglas de Arbitraje (Precio vs Complejidad)
            if score < 30: # Trivial
                if price < 1.0 and price < target_price: candidates.append(m)
            elif score <= 70: # Estándar
                if 0.5 < price < 5.0 and price < target_price: candidates.append(m)
        
        if not candidates:
            return requested_model, "NO_BETTER_OPTION", 0.0

        # GANADOR: El más barato que CUMPLE con Latencia y Contexto
        winner = min(candidates, key=lambda x: float(x.get('price_out', 0)))
        winner_id = winner['model']
        
        # Calcular ahorro real
        savings = (target_price - float(winner.get('price_out', 0))) / target_price if target_price > 0 else 0
        return winner_id, "SMART_ROUTING", savings

arbitrage_engine = WiseArbitrageEngine()
