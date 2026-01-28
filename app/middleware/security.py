import logging

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import settings

logger = logging.getLogger("agentshield.security")


async def security_guard_middleware(request: Request, call_next):
    # 1. Bypass para Health Check y modo Desarrollo
    # Determinamos si es desarrollo basándonos en el entorno configurado
    is_dev = settings.ENVIRONMENT == "development"

    if request.url.path == "/health" or request.method == "OPTIONS" or is_dev:
        return await call_next(request)

    # 2. VERIFICACIÓN DE CLOUDFLARE (El Candado)
    expected_secret = settings.model_dump().get("CLOUDFLARE_PROXY_SECRET")
    incoming_secret = request.headers.get("X-AgentShield-Auth")

    if expected_secret and incoming_secret != expected_secret:
        real_ip = request.headers.get("cf-connecting-ip", request.client.host)
        logger.warning(f"⛔ Direct access blocked from {real_ip}")
        return JSONResponse(
            status_code=403,
            content={"error": "Direct access forbidden. Use the authorized portal."},
        )

    # 3. PROCESAR PETICIÓN
    response = await call_next(request)

    # 4. INYECCIÓN HSTS (El Blindaje SSL)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # 5. CABECERAS EXTRA DE SEGURIDAD (Bonus Enterprise)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"

    return response
