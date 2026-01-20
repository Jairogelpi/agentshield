# agentshield_core/scripts/sync_prices.py
import asyncio
import os
import sys

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import redis.asyncio as redis
from supabase import create_client

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
redis_client = redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)


async def fetch_latest_prices():
    print("🔄 Sincronizando Precios + Context Windows (Async)...")
    try:
        # OpenRouter invocado con httpx o requests en hilo aparte si blocking,
        # pero para un script standalone, blocking requests aqui es aceptable
        # lo critico es redis.asyncio para consistencia.
        resp = requests.get("https://openrouter.ai/api/v1/models", timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])

        updates = []
        for model in data:
            full_id = model.get("id")
            pricing = model.get("pricing", {})
            context_length = int(model.get("context_length", 4096))

            parts = full_id.split("/")
            provider = parts[0] if len(parts) > 1 else "openrouter"
            m_id = parts[1] if len(parts) > 1 else full_id

            try:
                p_in = float(pricing.get("prompt", 0))
                p_out = float(pricing.get("completion", 0))
            except:
                continue

            if p_in >= 0:
                updates.append(
                    {
                        "provider": provider,
                        "model": m_id,
                        "price_in": p_in,
                        "price_out": p_out,
                        "context_window": context_length,
                        "is_active": True,
                        "updated_at": "now()",
                    }
                )

        if updates:
            print(f"📦 Actualizando {len(updates)} modelos...")
            batch_size = 500
            for i in range(0, len(updates), batch_size):
                supabase.table("model_prices").upsert(
                    updates[i : i + batch_size], on_conflict="provider, model"
                ).execute()

            # Limpieza de caché Redis (Async)
            async for key in redis_client.scan_iter(match="price:*"):
                await redis_client.delete(key)

            await redis_client.delete("market:active_models")
            await redis_client.delete("market:active_models_v2")

            print("✅ Sincronización Inteligente Completada.")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await redis_client.close()


if __name__ == "__main__":
    asyncio.run(fetch_latest_prices())
