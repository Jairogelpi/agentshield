import logging

from fastapi import HTTPException, Request

from app.config import settings
from app.db import redis_client
from app.limiter import get_real_ip_address
from app.logic import verify_api_key
from app.services.event_bus import event_bus

logger = logging.getLogger("agentshield.auth")


async def global_security_guard(request: Request):
    # 0. RECOLECCIÓN DE TELEMETRÍA
    path = request.url.path
    trace_id = getattr(request.state, "trace_id", "TRC-UNKNOWN")
    client_ip = get_real_ip_address(request)

    # 1. Whitelist con soporte de prefijos (para /docs/, /health/, etc.)
    if any(path.startswith(prefix) for prefix in settings.AUTH_WHITELIST):
        return

    if request.method == "OPTIONS":
        return

    # 2. Protección Brute Force (Pre-auth IP Check)
    block_key = f"auth_block:{client_ip}"

    try:
        if await redis_client.get(block_key):
            logger.warning(
                f"🛑 [Block] Brute Force attempt blocked from {client_ip} | Trace: {trace_id}"
            )

            # SIEM ALERT (Info level since it's already blocked)
            await event_bus.publish(
                tenant_id="SYSTEM",
                event_type="AUTH_BRUTE_FORCE_BLOCKED",
                severity="INFO",
                details={"ip": client_ip, "reason": "Previous limit reached"},
                trace_id=trace_id,
            )

            raise HTTPException(
                429, "Too many failed authentication attempts. Please try again later."
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"⚠️ [Auth] Redis error in Brute Force check: {e} | Trace: {trace_id}")
        # Degradamos suavemente: Permitimos continuar si Redis falla (Disponibilidad > Brute Force)

    # 3. Exigir credenciales e Inyectar Estado
    try:
        tenant_id = await verify_api_key(request.headers.get("Authorization"))
        request.state.tenant_id = tenant_id

        # Limpieza de fallos si la auth es exitosa
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

            # SIEM ALERT (Warning)
            await event_bus.publish(
                tenant_id="SYSTEM",
                event_type="AUTH_FAILURE",
                severity="WARNING",
                details={"ip": client_ip, "fails_count": fails},
                trace_id=trace_id,
            )

            if fails >= settings.AUTH_BRUTE_FORCE_LIMIT:
                await redis_client.setex(block_key, settings.AUTH_BRUTE_FORCE_WINDOW, "blocked")
                logger.error(
                    f"🚨 [Auth] IP {client_ip} reached fail limit ({fails}). Blocking. | Trace: {trace_id}"
                )
                # SIEM ALERT (Critical)
                await event_bus.publish(
                    tenant_id="SYSTEM",
                    event_type="AUTH_BRUTE_FORCE_LIMIT_REACHED",
                    severity="CRITICAL",
                    details={"ip": client_ip, "limit": settings.AUTH_BRUTE_FORCE_LIMIT},
                    trace_id=trace_id,
                )
        except Exception as re:
            logger.error(f"⚠️ Could not update Brute Force counter: {re} | Trace: {trace_id}")

        raise e
