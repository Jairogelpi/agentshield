import asyncio
import functools
import logging

from app.services.cache import get_semantic_cache, set_semantic_cache

logger = logging.getLogger("agentshield.decorators")


def semantic_cache(threshold: float = 0.90):
    """
    Decorador para funciones async que toman un 'prompt' (o primer arg string)
    y devuelven un string. Cachea semánticamente la respuesta.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 1. Heurística para encontrar el Prompt
            prompt = kwargs.get("prompt") or kwargs.get("content")
            if not prompt and args and isinstance(args[0], str):
                prompt = args[0]

            # Intentamos extraer tenant_id si está disponible
            tenant_id = (
                kwargs.get("tenant_id") or getattr(args[0], "tenant_id", "*")
                if args and hasattr(args[0], "tenant_id")
                else "*"
            )

            if prompt:
                # 2. Check Cache
                # Pasamos tenant_id para respetar la privacidad si se implementa
                cached = await get_semantic_cache(prompt, threshold, tenant_id=tenant_id)
                if cached:
                    logger.info(f"⚡ Semantic Cache HIT for: {prompt[:30]}...")
                    return cached

            # 3. Ejecución Real
            response = await func(*args, **kwargs)

            # 4. Guardado Asíncrono (Fire & Forget)
            if prompt and response and isinstance(response, str):
                # Solo cacheamos si la respuesta es válida y string
                asyncio.create_task(set_semantic_cache(prompt, response, tenant_id))

            return response

        return wrapper

    return decorator
