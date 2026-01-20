# agentshield_core/app/limiter.py
import hashlib
import logging
import os

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

# Configuración del Logger
logger = logging.getLogger("agentshield.limiter")


def get_real_ip_address(request: Request):
    """
    Obtiene la IP real del usuario detrás de Cloudflare.
    Usado como fallback para usuarios anónimos.
    """
    # 1. Cloudflare (Estándar Gratis)
    if request.headers.get("cf-connecting-ip"):
        return request.headers.get("cf-connecting-ip")

    # 2. Otros proxies (Fallback)
    if request.headers.get("x-forwarded-for"):
        return request.headers.get("x-forwarded-for").split(",")[0]

    # 3. Desarrollo local
    return get_remote_address(request)


def get_tenant_rate_limit_key(request: Request):
    """
    Estrategia "Corporate-Ready": Limita por Identidad, no por IP.
    Evita el problema del "Vecino Ruidoso" en redes corporativas (NAT).
    """
    # 1. Prioridad: API Key / Token (Bearer ...)
    auth = request.headers.get("Authorization")
    if auth:
        # Usamos MD5 para tener una clave corta y consistente en Redis.
        # No es por seguridad criptográfica, es por eficiencia de almacenamiento y lookup.
        return hashlib.md5(auth.encode()).hexdigest()

    # 2. Prioridad: Function ID (Para scripts específicos sin Auth estándar)
    func_id = request.headers.get("X-Function-ID")
    if func_id:
        return func_id

    # 3. Fallback: IP Real (Solo para tráfico anónimo/público)
    return get_real_ip_address(request)


# Inicializamos el Limiter con Redis
raw_redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

# DEBUG: Ver qué está llegando realmente (Sanitized Log)
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

logger.info(
    f"✅ LIMITER: Normalized URL for Limits: {redis_url.split('://')[0]}://...@{redis_url.split('@')[-1] if '@' in redis_url else 'LOCAL'}"
)

# INSTANCIA FINAL
# Usamos la nueva key_func inteligente
limiter = Limiter(key_func=get_tenant_rate_limit_key, storage_uri=redis_url)
