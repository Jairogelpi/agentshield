# agentshield_core/app/limiter.py
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request
import os

def get_real_ip_address(request: Request):
    """
    Obtiene la IP real del usuario detrás de Cloudflare.
    """
    # 1. Cloudflare (Estándar Gratis)
    if request.headers.get("cf-connecting-ip"):
        return request.headers.get("cf-connecting-ip")
    
    # 2. Otros proxies (Fallback)
    if request.headers.get("x-forwarded-for"):
        return request.headers.get("x-forwarded-for").split(",")[0]
        
    # 3. Desarrollo local
    return get_remote_address(request)

import logging
logger = logging.getLogger("agentshield.limiter")

# Inicializamos el Limiter
raw_redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

# DEBUG: Ver qué está llegando realmente
masked_url = raw_redis_url.split("@")[-1] if "@" in raw_redis_url else "LOCAL"
logger.info(f"🔍 LIMITER: Raw REDIS_URL detected: ...@{masked_url}")

# 1. Limpieza agresiva (Quotes, Whitespace)
redis_url = raw_redis_url.strip().strip("'").strip('"')

# 2. Sanitización de Esquema (Limits no soporta +async)
if "redis+async" in redis_url:
    redis_url = redis_url.replace("redis+async", "redis")

# Handle rediss (SSL) cases too
if "rediss+async" in redis_url:
    redis_url = redis_url.replace("rediss+async", "rediss")
    
logger.info(f"✅ LIMITER: Normalized URL for Limits: {redis_url.split('://')[0]}://...@{redis_url.split('@')[-1] if '@' in redis_url else 'LOCAL'}")

limiter = Limiter(
    key_func=get_real_ip_address, 
    storage_uri=redis_url
)
