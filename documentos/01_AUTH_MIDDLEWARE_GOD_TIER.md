# 🛡️ Middleware de Autenticación: Nivel God Tier

Este documento detalla el funcionamiento del "Portero de AgentShield", un sistema de seguridad avanzado que combina flexibilidad, protección activa y alto rendimiento.

---

## 🚀 Mejoras de Nivel "God Tier" Implementadas

Hemos transformado el middleware básico en un sistema de grado empresarial con tres innovaciones críticas:

1.  **Optimización de Whitelist (Prefix Matching):** Ya no usamos comparaciones exactas. Ahora soportamos prefijos, permitiendo que rutas como `/docs/static/...` o `/health/check` sean públicas automáticamente sin configuraciones manuales tediosas.
2.  **Protección Brute Force Integrada:** El middleware monitoriza fallos de autenticación por IP en tiempo real usando Redis. Si detecta un ataque coordinado, bloquea la IP por completo antes de que pueda saturar la base de datos o el motor de IA.
3.  **Inyección de Estado (Zero-Latency Auth):** Una vez que el middleware valida la identidad, "inyecta" el ID del tenant en el objeto de la petición (`request.state`). Esto elimina la necesidad de que los routers vuelvan a validar la API Key, reduciendo la latencia de cada llamada en milisegundos críticos.

---

## 📄 El Código de Elite (`app/middleware/auth.py`)

A continuación se muestra el archivo completo con sus protecciones:

```python
import logging
from fastapi import HTTPException, Request
from app.config import settings
from app.db import redis_client
from app.limiter import get_real_ip_address
from app.logic import verify_api_key

logger = logging.getLogger("agentshield.auth")

async def global_security_guard(request: Request):
    # 1. Whitelist con soporte de prefijos (God Tier #1)
    path = request.url.path
    if any(path.startswith(prefix) for prefix in settings.AUTH_WHITELIST):
        return

    if request.method == "OPTIONS":
        return

    # 2. Protección Brute Force - Pre-auth IP Check (God Tier #2)
    client_ip = get_real_ip_address(request)
    block_key = f"auth_block:{client_ip}"
    
    if await redis_client.get(block_key):
        logger.warning(f"🛑 Blocked request from {client_ip} (Brute Force Protection)")
        raise HTTPException(429, "Too many failed authentication attempts. Please try again later.")

    # 3. Exigir credenciales e Inyectar Estado (God Tier #3)
    try:
        tenant_id = await verify_api_key(request.headers.get("Authorization"))
        
        # Inyectamos en el estado para que los routers no tengan que validar de nuevo
        request.state.tenant_id = tenant_id
        
        # Si tiene éxito, limpiamos el contador de fallos para ser justos
        await redis_client.delete(f"auth_fail:{client_ip}")
        
    except HTTPException as e:
        # 4. Contador de Fallos (Brute Force Detection)
        fail_key = f"auth_fail:{client_ip}"
        fails = await redis_client.incr(fail_key)
        
        if fails == 1:
            await redis_client.expire(fail_key, settings.AUTH_BRUTE_FORCE_WINDOW)
            
        if fails >= settings.AUTH_BRUTE_FORCE_LIMIT:
            # Bloqueo total por el tiempo definido en la configuración
            await redis_client.setex(block_key, settings.AUTH_BRUTE_FORCE_WINDOW, "blocked")
            logger.error(f"🚨 IP {client_ip} reached fail limit ({fails}). Blocking for {settings.AUTH_BRUTE_FORCE_WINDOW}s")
            
        raise e
```

---

## 🧠 ¿Cómo funciona la Inyección de Estado?

En los routers (como `authorize.py`), ya no tienes que hacer esto:
❌ `tenant_id = await verify_api_key(headers.authorization)`

Ahora el router simplemente hace esto:
✅ `tenant_id = request.state.tenant_id`

**Beneficio:** Una sola validación por cada "viaje" al servidor. Menos carga en Redis, menos carga en la DB, y una experiencia mucho más fluida para el usuario final.
