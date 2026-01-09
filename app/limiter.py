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

# Inicializamos el Limiter
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

# Usamos redis:// estándar (Limits gestiona el pool)
# if redis_url.startswith("redis://"):
#    redis_url = redis_url.replace("redis://", "redis+async://")

limiter = Limiter(
    key_func=get_real_ip_address, 
    storage_uri=redis_url
)
