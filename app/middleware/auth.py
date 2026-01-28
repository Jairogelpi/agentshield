import logging
from fastapi import Request, HTTPException
from app.logic import verify_api_key

logger = logging.getLogger("agentshield.auth")

async def global_security_guard(request: Request):
    # Lista blanca de endpoints backend que NO requieren auth
    whitelist = [
        "/health",
        "/docs",
        "/openapi.json",
        "/v1/webhook",
        "/v1/public/tenant-config",
        "/v1/signup",
        "/v1/onboarding/organizations",
        "/v1/onboarding/invite",
    ]

    if request.url.path in whitelist:
        return

    if request.method == "OPTIONS":
        return

    # Exigir credenciales
    await verify_api_key(request.headers.get("Authorization"))
