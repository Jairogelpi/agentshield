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

def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    Calcula el coste estimado en USD basado en el modelo y tokens.
    """
    # Buscar el modelo exacto o el más cercano
    config = PRICING_TABLE.get("default")
    model_lower = model.lower()
    
    for key, values in PRICING_TABLE.items():
        if key in model_lower:
            config = values
            break
            
    input_cost = (prompt_tokens / 1_000_000) * config["input"]
    output_cost = (completion_tokens / 1_000_000) * config["output"]
    
    return round(input_cost + output_cost, 6)
