import logging

import uuid
from fastapi import HTTPException, Request, Response
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
    expected_secret = settings.CLOUDFLARE_PROXY_SECRET
    incoming_secret = request.headers.get("X-AgentShield-Auth")

    if expected_secret and incoming_secret != expected_secret:
        real_ip = request.headers.get("cf-connecting-ip", request.client.host)
        logger.warning(f"⛔ Direct access blocked from {real_ip}")
        return JSONResponse(
            status_code=403,
            content={"error": "Direct access forbidden. Use the authorized portal."},
        )

    # 3. OBSERVABILIDAD (X-Request-ID)
    # Generamos un ID único para trazabilidad si no viene del proxy (Cloudflare)
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.trace_id = request_id

    # 4. PROCESAR PETICIÓN
    response = await call_next(request)

    # 5. INYECCIÓN HSTS (El Blindaje SSL)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # 6. CABECERAS EXTRA DE SEGURIDAD (Bonus Enterprise)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Request-ID"] = request_id

    return response
