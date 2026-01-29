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
 
 
 from app.config import settings
 
 # Inicializamos el Limiter con Redis
 # Normalizamos la URL para el motor de 'limits' (no soporta +async)
 redis_url = settings.REDIS_URL.replace("redis+async", "redis").replace("rediss+async", "rediss")
 
 # INSTANCIA FINAL
 # Usamos la nueva key_func inteligente
 limiter = Limiter(key_func=get_tenant_rate_limit_key, storage_uri=redis_url)
