import httpx
import logging
from app.db import supabase, redis_client

# Configuración
PRICING_SOURCE_URL = "https://openrouter.ai/api/v1/models"

logger = logging.getLogger("agentshield.pricing")

async def sync_prices_from_openrouter():
    """
    Sincronización 'Zero-Downtime'. 
    Actualiza la Source of Truth (DB) y luego invalida Redis sin bloquear el servidor.
    """
    logger.info("⏳ Iniciando sincronización de precios...")
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(PRICING_SOURCE_URL, timeout=10.0)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            
            updates_list = []
            
            # 1. Preparación de datos en memoria (Más rápido que ir 1 a 1 a la DB)
            for model_info in data:
                full_id = model_info.get("id", "")
                parts = full_id.split("/")
                provider = parts[0] if len(parts) == 2 else "openrouter"
                model_name = parts[1] if len(parts) == 2 else full_id
                
                pricing = model_info.get("pricing", {})
                try:
                    price_in = float(pricing.get("prompt", 0))
                    price_out = float(pricing.get("completion", 0))
                except:
                    continue
                
                if price_in < 0: continue

                updates_list.append({
                    "provider": provider,
                    "model": model_name,
                    "price_in": price_in,
                    "price_out": price_out,
                    "is_active": True,
                    "updated_at": "now()"
                })

            if not updates_list:
                return {"status": "no_changes"}

            # 2. UPSERT Masivo en DB (Batch Processing)
            # Supabase soporta upsert masivo, mucho más eficiente que el loop anterior
            # Procesamos en lotes de 1000 para no exceder límites de payload HTTP
            batch_size = 1000
            for i in range(0, len(updates_list), batch_size):
                batch = updates_list[i:i + batch_size]
                supabase.table("model_prices").upsert(batch, on_conflict="provider, model").execute()

            # 3. INVALIDACIÓN INTELIGENTE (SCAN_ITER + UNLINK) [Tecnología 2026]
            # scan_iter maneja el cursor internamente y es un generador seguro
            batch_keys = []
            deleted_count = 0
            
            # Iteramos sobre todas las claves que coinciden
            async for key in redis_client.scan_iter(match="price:*", count=1000):
                batch_keys.append(key)
                # Borramos en lotes para no llenar la memoria de la lista
                if len(batch_keys) >= 1000:
                    await redis_client.unlink(*batch_keys)
                    deleted_count += len(batch_keys)
                    batch_keys = []
            
            # Borrar remanentes
            if batch_keys:
                await redis_client.unlink(*batch_keys)
                deleted_count += len(batch_keys)
            
            logger.info(f"✅ Sincronización completada. {len(updates_list)} actualizados en DB. {deleted_count} invalidados en Redis.")
            return {"status": "success", "updated": len(updates_list), "cache_cleared": deleted_count}
            
        except Exception as e:
            logger.error(f"❌ Error syncing prices: {e}")
            return {"status": "error", "message": str(e)}
