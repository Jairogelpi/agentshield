import httpx
import logging
from app.db import supabase, redis_client

# Configuración
PRICING_SOURCE_URL = "https://openrouter.ai/api/v1/models"

logger = logging.getLogger("agentshield.pricing")

async def sync_prices_from_openrouter():
    """
    Descarga los precios actualizados de OpenRouter (Aggregator líder)
    y actualiza la tabla local 'model_prices' (Source of Truth).
    """
    logger.info("⏳ Iniciando sincronización de precios desde OpenRouter...")
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(PRICING_SOURCE_URL, timeout=10.0)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            
            updates_count = 0
            
            for model_info in data:
                # OpenRouter ID format: "openai/gpt-4"
                # Nosotros usamos provider="openai", model="gpt-4"
                # Vamos a intentar parsear o guardar el mapping.
                
                full_id = model_info.get("id", "")
                parts = full_id.split("/")
                
                if len(parts) == 2:
                    provider = parts[0]
                    model_name = parts[1]
                else:
                    # Caso fallback o modelos sin provider claro
                    provider = "openrouter"
                    model_name = full_id
                
                pricing = model_info.get("pricing", {})
                
                # Precios en OpenRouter suelen ser por token (raw)
                # A veces string, a veces float.
                try:
                    price_in = float(pricing.get("prompt", 0))
                    price_out = float(pricing.get("completion", 0))
                except:
                    continue
                
                if price_in <= 0 and price_out <= 0:
                    continue
                    
                # UPSERT en nuestra DB
                # Usamos una query raw o supabase-py si soporta upsert
                # Supabase-py upsert requiere pasar todos los campos obligatorios
                
                record = {
                    "provider": provider,
                    "model": model_name,
                    "price_in": price_in,
                    "price_out": price_out,
                    "is_active": True,
                    "updated_at": "now()"
                }
                
                # Upsert basado en restricción única (provider, model)
                supabase.table("model_prices").upsert(record, on_conflict="provider, model").execute()
                
                # Invalidad caché de Redis
                redis_client.delete(f"price:{model_name}")
                redis_client.delete(f"price:{provider}/{model_name}") # Por si acaso
                
                updates_count += 1
                
            logger.info(f"✅ Sincronización completada. {updates_count} modelos actualizados.")
            return {"status": "success", "updated": updates_count}
            
        except Exception as e:
            logger.error(f"❌ Error syncing prices: {e}")
            return {"status": "error", "message": str(e)}
