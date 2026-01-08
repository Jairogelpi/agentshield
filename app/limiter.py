# app/limiter.py
import os
from slowapi import Limiter
from slowapi.util import get_remote_address

# Inicializamos el Limiter conectado a Redis
# Si no hay REDIS_URL, usará memoria (MemoryStorage), pero en producción DEBE usar Redis.
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

limiter = Limiter(
    key_func=get_remote_address, 
    storage_uri=redis_url
)
