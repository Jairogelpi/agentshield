import logging
import os
import time
import uuid

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.event_bus import event_bus

logger = logging.getLogger("agentshield.security")


async def security_guard_middleware(request: Request, call_next):
    # 0. TELEMETRÍA INICIAL (The Zenith Anchor)
    # Marcamos el inicio exacto para medir latencias en el HUD/Dashboard
    request.state.start_ts = time.time()
    
    # Bypass para Health Check y modo Desarrollo
    is_dev = settings.ENVIRONMENT == "development"
    if request.url.path == "/health" or request.method == "OPTIONS" or is_dev:
        return await call_next(request)

    # 1. IDENTIDAD DE LA PETICIÓN (X-Request-ID)
    # Propagamos el ID de Cloudflare o generamos uno nuevo
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.trace_id = request_id

    # 2. VERIFICACIÓN DE CLOUDFLARE (El Candado)
    expected_secret = settings.CLOUDFLARE_PROXY_SECRET
    incoming_secret = request.headers.get("X-AgentShield-Auth")

    if expected_secret and incoming_secret != expected_secret:
        real_ip = request.headers.get("cf-connecting-ip", request.client.host)
        logger.warning(f"⛔ Unauthorized Direct Access [{request_id}] from {real_ip}")
        
        return JSONResponse(
            status_code=403,
            content={
                "error": "Security Breach detected",
                "message": "Direct access forbidden. Use the authorized portal.",
                "trace_id": request_id
            }
        )

    # 3. PROCESAR PETICIÓN (El Túnel)
    response = await call_next(request)

    # 4. BLINDAJE DE SEGURIDAD (Zenith Header Protocol 2026)
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["X-Request-ID"] = request_id
    response.headers["X-AgentShield-Region"] = os.getenv("SERVER_REGION", "EU-WEST-CONT")

    return response
