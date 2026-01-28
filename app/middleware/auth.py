import logging

from fastapi import HTTPException, Request

from app.config import settings
from app.db import redis_client
from app.limiter import get_real_ip_address
from app.logic import verify_api_key

logger = logging.getLogger("agentshield.auth")


async def global_security_guard(request: Request):
    # 1. Whitelist con soporte de prefijos (para /docs/, /health/, etc.)
    path = request.url.path
    if any(path.startswith(prefix) for prefix in settings.AUTH_WHITELIST):
        return

    if request.method == "OPTIONS":
        return

    # 2. Protección Brute Force (Pre-auth IP Check)
    client_ip = get_real_ip_address(request)
    block_key = f"auth_block:{client_ip}"

    try:
        if await redis_client.get(block_key):
            logger.warning(f"🛑 Blocked request from {client_ip} (Brute Force Protection)")
            raise HTTPException(
                429, "Too many failed authentication attempts. Please try again later."
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"⚠️ Redis error in Brute Force check: {e}")
        # Degradamos suavemente: Permitimos continuar si Redis falla (Disponibilidad > Brute Force)

    # 3. Exigir credenciales e Inyectar Estado
    try:
        tenant_id = await verify_api_key(request.headers.get("Authorization"))

        # Inyectamos en el estado para que los routers no tengan que validar de nuevo
        request.state.tenant_id = tenant_id

        # Si tiene éxito, intentamos limpiar el contador de fallos
        try:
            await redis_client.delete(f"auth_fail:{client_ip}")
        except:
            pass

    except HTTPException as e:
        # 4. Contador de Fallos (Brute Force Detection)
        fail_key = f"auth_fail:{client_ip}"
        try:
            fails = await redis_client.incr(fail_key)
            if fails == 1:
                await redis_client.expire(fail_key, settings.AUTH_BRUTE_FORCE_WINDOW)

            if fails >= settings.AUTH_BRUTE_FORCE_LIMIT:
                await redis_client.setex(block_key, settings.AUTH_BRUTE_FORCE_WINDOW, "blocked")
                logger.error(
                    f"🚨 IP {client_ip} reached fail limit ({fails}). Blocking for {settings.AUTH_BRUTE_FORCE_WINDOW}s"
                )
        except Exception as re:
            logger.error(f"⚠️ Could not update Brute Force counter in Redis: {re}")

        raise e
