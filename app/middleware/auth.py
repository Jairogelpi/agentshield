import logging
from fastapi import Request, HTTPException
from app.logic import verify_api_key
from app.config import settings

logger = logging.getLogger("agentshield.auth")

async def global_security_guard(request: Request):
    # Usar whitelist configurada en settings
    if request.url.path in settings.AUTH_WHITELIST:
        return

    if request.method == "OPTIONS":
        return

    # Exigir credenciales
    await verify_api_key(request.headers.get("Authorization"))
