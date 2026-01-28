import asyncio
import logging
from typing import Optional

import httpx
from litellm import model_cost  # <--- LA FUENTE DE LA VERDAD

from app.db import redis_client, supabase

# Configuración
logger = logging.getLogger("agentshield.pricing")


async def sync_universal_prices():
    """
    Sincronización Híbrida:
    1. LiteLLM Internal (Prioridad Máxima): Sincroniza lo que la librería tiene en memoria.
    2. OpenRouter API (Fallback): Para modelos nuevos que LiteLLM aun no tiene hardcoded.
    """
    logger.info("⚡ Iniciando Protocolo Espejo (LiteLLM + OpenRouter)...")

    updates_map = {}  # Usamos dict para evitar duplicados, clave = model_name

    # --- FASE 1: EXTRACCIÓN DIRECTA DE LITELLM ---
    # Esto garantiza que tus cobros sean idénticos a los costes técnicos
    try:
        logger.info(f"🔮 Leyendo {len(model_cost)} modelos internos de LiteLLM...")

        for model_name, info in model_cost.items():
            try:
                # Normalizamos precios
                p_in = float(info.get("input_cost_per_token", 0))
                p_out = float(info.get("output_cost_per_token", 0))

                if p_in == 0 and p_out == 0:
                    continue

                # Detectar proveedor
                provider = "generic"
                if "litellm_provider" in info:
                    provider = info["litellm_provider"]
                elif "/" in model_name:
                    provider = model_name.split("/")[0]

                updates_map[model_name] = {
                    "provider": provider,
                    "model": model_name,
                    "price_in": p_in,
                    "price_out": p_out,
                    "is_active": True,
                    "updated_at": "now()",
                }
            except Exception:
                continue
    except Exception as e:
        logger.error(f"⚠️ Error leyendo LiteLLM internals: {e}")

    # --- FASE 2: API OPENROUTER (Para modelos exóticos) ---
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://openrouter.ai/api/v1/models", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                for item in data:
                    model_id = item.get("id")
                    # Solo añadimos si NO estaba ya en LiteLLM (LiteLLM manda)
                    if model_id not in updates_map:
                        pricing = item.get("pricing", {})
                        updates_map[model_id] = {
                            "provider": model_id.split("/")[0],
                            "model": model_id,
                            "price_in": float(pricing.get("prompt", 0)),
                            "price_out": float(pricing.get("completion", 0)),
                            "is_active": True,
                            "updated_at": "now()",
                        }
    except Exception as e:
        logger.warning(f"⚠️ OpenRouter sync skipped: {e}")

    # --- FASE 3: PERSISTENCIA MASIVA ---
    if not updates_map:
        return {"status": "no_changes"}

    updates_list = list(updates_map.values())

    try:
        # 3.1 DB Upsert (Lotes)
        batch_size = 1000
        for i in range(0, len(updates_list), batch_size):
            batch = updates_list[i : i + batch_size]
            # Upsert ignorando conflictos
            supabase.table("model_prices").upsert(batch, on_conflict="provider, model").execute()

        # 3.2 Redis Cache Warming (Opcional: Pre-cargar los más usados)
        # Invertimos en llamadas 'set' para tener los precios calientes YA.
        # Usamos pipeline para velocidad.
        pipe = redis_client.pipeline()
        for item in updates_list:
            # Key simple para acceso O(1)
            cache_key = f"price:{item['model']}"
            val = f"{item['price_in']}|{item['price_out']}"
            pipe.setex(cache_key, 86400 * 7, val)  # 1 semana de cache

        await pipe.execute()

        logger.info(
            f"✅ Sincronización Universal Completada: {len(updates_list)} modelos actualizados."
        )
        return {"status": "success", "count": len(updates_list)}

    except Exception as e:
        logger.error(f"❌ DB Write Error: {e}")
        return {"status": "error", "message": str(e)}


async def audit_and_correct_price(model: str, used_p_in: float, used_p_out: float):
    """
    Se llama desde el Proxy cuando detectamos una discrepancia en vivo.
    Actualiza Redis/DB 'on-the-fly'.
    """
    try:
        cache_key = f"price:{model}"
        # Verificar qué tenemos en Redis
        cached = await redis_client.get(cache_key)

        needs_update = True
        if cached:
            c_in, c_out = map(float, cached.split("|"))
            # Usamos una tolerancia pequeña por errores de coma flotante
            if abs(c_in - used_p_in) < 1e-9 and abs(c_out - used_p_out) < 1e-9:
                needs_update = False

        if needs_update:
            logger.warning(f"🔧 AUTO-CORRECCIÓN DE PRECIO para {model}: {used_p_in}/{used_p_out}")
            # Actualizar Redis (Instantáneo)
            await redis_client.setex(cache_key, 86400 * 7, f"{used_p_in}|{used_p_out}")

            # Actualizar DB (Background) - Usamos un provider genérico si no lo sabemos
            provider = model.split("/")[0] if "/" in model else "unknown"
            asyncio.create_task(_async_db_update(provider, model, used_p_in, used_p_out))

    except Exception as e:
        logger.error(f"Audit failed: {e}")


async def _async_db_update(provider, model, p_in, p_out):
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: supabase.table("model_prices")
            .upsert(
                {
                    "provider": provider,
                    "model": model,
                    "price_in": p_in,
                    "price_out": p_out,
                    "updated_at": "now()",
                },
                on_conflict="provider, model",
            )
            .execute(),
        )
    except Exception as e:
        logger.error(f"Async DB Price Update failed: {e}")


async def get_model_pricing(model: str) -> dict:
    """
    Recupera los precios de entrada y salida para un modelo.
    Prioridad: Redis (O(1)) -> Supabase (O(N)) -> Fallback Seguro.
    """
    cache_key = f"price:{model}"
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            p_in, p_out = map(float, cached.decode().split("|"))
            return {"price_in": p_in, "price_out": p_out}
    except Exception as e:
        logger.error(f"Redis pricing lookup failed: {e}")

    # Fallback a DB
    try:
        res = (
            supabase.table("model_prices")
            .select("price_in, price_out")
            .eq("model", model)
            .maybe_single()
            .execute()
        )
        if res.data:
            return {"price_in": res.data["price_in"], "price_out": res.data["price_out"]}
    except Exception as e:
        logger.error(f"DB pricing lookup failed: {e}")

    # Fallback de Seguridad (Precios promedios 2026)
    return {"price_in": 0.00001, "price_out": 0.00003}
