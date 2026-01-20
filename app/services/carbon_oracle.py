# app/services/carbon_oracle.py
import httpx
import logging
from app.db import redis_client
from app.utils import fast_json as json

logger = logging.getLogger("agentshield.carbon_oracle")

# URL de la API de Carbon Intensity (UK - El más estable y gratuito para demos)
# En producción, esto se cambiaría por Electricity Maps API con su API Key
CARBON_API_URL = "https://api.carbonintensity.org.uk/intensity"

async def fetch_real_carbon_intensity() -> float:
    """
    Obtiene la intensidad de carbono actual (gCO2/kWh) de una fuente pública real.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(CARBON_API_URL, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            
            # Formato esperado: {"data": [{"intensity": {"actual": 123}}]}
            intensity = data["data"][0]["intensity"]["actual"]
            
            logger.info(f"🌿 Real-time Carbon Intensity Fetched: {intensity} gCO2/kWh")
            
            # Cacheamos el valor global
            await redis_client.set("oracle:carbon:intensity", str(intensity), ex=1800) # 30 mins
            return float(intensity)
            
    except Exception as e:
        logger.error(f"❌ Failed to fetch carbon intensity API: {e}")
        # Intentamos recuperar del cache si la API falló
        cached = await redis_client.get("oracle:carbon:intensity")
        return float(cached) if cached else 300.0 # Valor promedio global si todo falla

async def get_current_intensity() -> float:
    cached = await redis_client.get("oracle:carbon:intensity")
    if cached:
        return float(cached)
    return await fetch_real_carbon_intensity()

carbon_oracle = fetch_real_carbon_intensity
