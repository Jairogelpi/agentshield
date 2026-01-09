# agentshield_core/app/services/carbon.py

# Intensidad de Carbono (gCO2eq/kWh) aproximada por región (Datos 2025)
REGION_CARBON_INTENSITY = {
    "eu": 250.0, # Europa (Mix variado)
    "us": 380.0, # USA (Mayor dependencia fósil)
    "green-cloud": 50.0 # Regiones "Carbon Neutral" específicas
}

# Consumo estimado por 1K tokens (kWh) - Heurística basada en tamaño de parámetros
MODEL_ENERGY_FACTOR = {
    "gpt-4": 0.005,      # Muy pesado
    "claude-3-opus": 0.005,
    "gpt-3.5-turbo": 0.0008, # Ligero
    "llama-3-8b": 0.0006,    # Muy ligero (Edge)
    "default": 0.001
}

def calculate_footprint(model: str, region: str, tokens_total: int) -> float:
    """
    Devuelve los gramos de CO2 emitidos por esta petición.
    Fórmula: Energía (kWh) * Intensidad Carbono (gCO2/kWh)
    """
    # 1. Obtener factor del modelo
    # Normalizamos nombre (ej: gpt-4-0613 -> gpt-4)
    model_key = "default"
    for key in MODEL_ENERGY_FACTOR:
        if key in model.lower():
            model_key = key
            break
            
    factor = MODEL_ENERGY_FACTOR.get(model_key, MODEL_ENERGY_FACTOR["default"])
    
    # 2. Calcular energía (kWh)
    # tokens / 1000 * factor
    energy_kwh = (tokens_total / 1000.0) * factor
    
    # 3. Aplicar factor regional (PUE incluido en la constante)
    # Si la región no está, asumimos peor caso (US)
    intensity = REGION_CARBON_INTENSITY.get(region, 380.0)
    
    g_co2 = energy_kwh * intensity
    return round(g_co2, 6)

def calculate_extra_emission(orig_model: str, target_model: str) -> float:
    """
    Calcula cuántos gramos EXTRA de CO2 se emiten por usar el modelo original 
    en lugar del optimizado. Asume 1000 tokens promedio para la métrica.
    """
    # Usamos región 'eu' como baseline
    footprint_orig = calculate_footprint(orig_model, "eu", 1000)
    footprint_target = calculate_footprint(target_model, "eu", 1000)
    
    return max(0.0, footprint_orig - footprint_target)
