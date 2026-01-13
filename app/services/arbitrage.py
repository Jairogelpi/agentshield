# agentshield_core/app/services/arbitrage.py
from app.utils import fast_json as json
import logging
from litellm import acompletion
from app.db import redis_client, supabase
import numpy as np
from opentelemetry import trace
import random

tracer = trace.get_tracer(__name__)
logger = logging.getLogger("agentshield.arbitrage")

class AgentShieldRLArbitrator:
    def __init__(self):
        self.router_model = "groq/llama3-8b-8192"
        # RL Hyperparameters
        self.learning_rate = 0.05
        self.discount_factor = 0.9 # Bandit usually 0, but user requested 0.9
        self.epsilon = 0.1 # Exploration rate
        self.min_epsilon = 0.01
        self.epsilon_decay = 0.995

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

    def _get_state_key(self, complexity_score: float, input_tokens: int) -> str:
        """
        Discretiza el estado para la Q-Table.
        State = (ComplexityBucket, SizeBucket)
        """
        # Bucket Complejidad: 0-20 (Trivial), 20-50 (Simple), 50-80 (Medium), 80-100 (Hard)
        if complexity_score < 20: c_bucket = "TRIVIAL"
        elif complexity_score < 50: c_bucket = "SIMPLE"
        elif complexity_score < 80: c_bucket = "MEDIUM"
        else: c_bucket = "HARD"
        
        # Bucket Tamaño: <500, <2000, >2000
        if input_tokens < 500: s_bucket = "SMALL"
        elif input_tokens < 2000: s_bucket = "NORMAL"
        else: s_bucket = "HUGE"
        
        return f"{c_bucket}:{s_bucket}"

    async def get_q_value(self, state: str, action_model: str) -> float:
        """Recupera Q(s,a) de Redis"""
        key = f"rl:q:{state}:{action_model}"
        val = await redis_client.get(key)
        return float(val) if val else 0.0

    async def update_learning(self, state: str, action_model: str, reward: float):
        """
        Actualiza Q(s,a) usando la ecuación de Bellman (o Bandit update).
        Q(s,a) = Q(s,a) + alpha * (reward - Q(s,a))  [Bandit simplificado]
        """
        current_q = await self.get_q_value(state, action_model)
        new_q = current_q + self.learning_rate * (reward - current_q)
        
        key = f"rl:q:{state}:{action_model}"
        await redis_client.set(key, new_q)
        
        # Log learning
        logger.info(f"🧠 RL Update [{state}][{action_model}]: {current_q:.4f} -> {new_q:.4f} (Reward: {reward:.4f})")

    def calculate_reward(self, cost_saved: float, rerank_score: float, latency_ms: float, user_satisfaction=1.0) -> float:
        """
        Función de Recompensa 2026:
        Optimiza el ROI balanceando precisión (rerank) y coste.
        """
        # --- FIX: HUMILDAD ARTIFICIAL ---
        # Si no hay feedback explícito del usuario (1.0 por defecto), 
        # bajamos a 0.9 para incentivar que el sistema siga buscando mejoras.
        if user_satisfaction == 1.0: 
            user_satisfaction = 0.9
        # --------------------------------
        
        # Penalizamos latencia alta y baja precisión agresivamente
        # Rerank score > 0.95 es ideal. Si baja, penalizamos exponencialmente.
        precision_penalty = 1.0 if rerank_score > 0.95 else (rerank_score * 0.5)
        
        # Latencia: Sigmoide que penaliza fuerte > 500ms
        # 1.0 / (1.0 + exp(0.01 * (lat - 500))) -> 500ms=0.5, 0ms~1.0, 1000ms~0.0
        try:
             latency_penalty = 1.0 / (1.0 + np.exp(0.01 * (latency_ms - 500)))
        except OverflowError:
             latency_penalty = 0.0

        # El ROI es el ahorro (normalizado o real) multiplicado por la calidad
        # Asumimos cost_saved está en rango [0, 1] (pct) o absoluto bajo.
        # Boost de recompensa si ahorramos dinero CON calidad.
        reward = (cost_saved + 0.1) * precision_penalty * latency_penalty * user_satisfaction * 10
        return float(reward)

    async def analyze_complexity(self, messages: list) -> dict:
        """Juez IA (Sin cambios)"""
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

    async def record_latency(self, model: str, ms: float):
        # Stub para compatibilidad si alguien lo llama, pero el RL aprende de la recompensa global
        pass

    async def find_best_bidder(self, requested_model: str, analysis: dict, max_output_tokens: int = 1000, tenant_allowlist: list = None):
        """
        Selección basada en Deep RL (Contextual Bandit).
        """
        score = analysis.get("score", 100)
        input_tokens = analysis.get("input_tokens", 0)
        state = self._get_state_key(score, input_tokens)
        
        # Reglas base para seguridad
        market_models = await self._get_market_models()
        target = next((m for m in market_models if m['model'] == requested_model), None)
        target_price = float(target['price_out']) if target else 100.0
        
        # Candidatos válidos (Filtros duros de contexto y allowlist)
        candidates = []
        for m in market_models:
            m_id = m['model']
            context = int(m.get('context_window', 4096))
            if tenant_allowlist and m_id not in tenant_allowlist: continue
            if context < (input_tokens + max_output_tokens): continue
            candidates.append(m)
            
        if not candidates:
            return requested_model, "NO_OPTIONS", 0.0

        # Epsilon-Greedy Exploration
        # Con probabilidad epsilon, elegimos al azar para descubrir nuevas eficiencias
        if random.random() < self.epsilon:
            winner = random.choice(candidates)
            reason = "RL_EXPLORATION"
        else:
            # Exploitation: Elegimos el modelo con mayor Q-Value
            best_q = -float('inf')
            winner = candidates[0]
            
            for cand in candidates:
                q = await self.get_q_value(state, cand['model'])
                # Factor de precio básico: Si no hay info RL, preferimos barato
                if q == 0.0:
                    price = float(cand.get('price_out', 0))
                    # Heurística inicial: Q inverso al precio (más barato = mejor start)
                    q = 1.0 / (price + 0.1)
                
                if q > best_q:
                    best_q = q
                    winner = cand
            reason = "RL_EXPLOITATION"

        winner_id = winner['model']
        savings = (target_price - float(winner.get('price_out', 0))) / target_price if target_price > 0 else 0
        
        # Enriquecemos el análisis con el estado para que el proxy pueda hacer el feedback
        analysis["rl_state"] = state
        
        return winner_id, reason, savings

    async def get_potential_arbitrage_gain(self, original_model: str, prompt_complexity_score: float) -> tuple[float, str]:
        # Mantenemos lógica simple para FOMO metrics
        if prompt_complexity_score < 40:
             market = await self._get_market_models()
             original = next((m for m in market if m['model'] == original_model), None)
             price_orig = float(original.get('price_out', 0)) if original else 0.0
             if price_orig == 0: return 0.0, original_model
             
             candidates = [m for m in market if float(m.get('price_out',0)) < price_orig]
             if candidates:
                winner = min(candidates, key=lambda x: float(x.get('price_out', 0)))
                price_cheap = float(winner.get('price_out', 0))
                return (price_orig - price_cheap), winner['model']
        return 0.0, original_model

arbitrage_engine = AgentShieldRLArbitrator()

async def get_best_provider(target_quality: str, max_latency_ms: int = 2000, messages: list = [], input_tokens: int = 0) -> dict:
    """
    Public façade for the Arbitrage Engine.
    Used by the Proxy to determine if we should swap the model.
    """
    try:
        # 1. Analyze Complexity (AI Judge)
        # Only analyze if we have messages and it's worth it (e.g. not trivial ping)
        analysis = {}
        if messages:
            # We use the internal engine to analyze prompt complexity
            # This helps decide if we can downgrade to a cheaper model safely
            analysis = await arbitrage_engine.analyze_complexity(messages)
        else:
            # Fallback for when we don't want to parse messages deep
            analysis = {"score": 50, "input_tokens": input_tokens} # Default to 'Medium'
            
        # 2. Ask the Bandit (RL) who is the best provider right now
        winner_id, reason, savings = await arbitrage_engine.find_best_bidder(
            requested_model=target_quality,
            analysis=analysis
        )
        
        if winner_id != target_quality:
            # We found a better option!
            # We need to find the API base for this winner (Logic simplistic here, 
            # ideally find_best_bidder returns the full object)
            
            # Re-fetch models to get details (cached in Redis inside the class)
            market = await arbitrage_engine._get_market_models()
            winner_obj = next((m for m in market if m['model'] == winner_id), None)
            
            if winner_obj:
                logger.info(f"💰 Arbitrage Opportunity: {target_quality} -> {winner_id} (Reason: {reason}, Est. Savings: {savings*100:.1f}%)")
                return {
                    "model": winner_id,
                    "api_base": winner_obj.get("api_base"), # Might be None if it's a standard cloud provider
                    "provider": winner_obj.get("provider", "openai"),
                    "reason": reason,
                    "rl_state": analysis.get("rl_state") # <--- FIX: Retornar estado para feedback loop
                }
                
    except Exception as e:
        logger.error(f"Arbitrage Check Failed: {e}")
        
    # Default: No swap
    return None
