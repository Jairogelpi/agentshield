# 🛡️ El Guardián de la Frontera: Auth Middleware (God Tier)

Este no es solo un archivo de "login"; es el **filtro de seguridad más crítico** de todo AgentShield. Si este archivo falla, el búnker queda abierto. Si este archivo es lento, todo el búnker es lento. Por eso, su diseño es "God Tier": combina protección militar con velocidad de competición.

---

## 🎯 ¿Para qué sirve este archivo? (El Propósito)

En una aplicación de IA, el coste y la seguridad son los mayores riesgos. Un atacante podría vaciar tu presupuesto de tokens en segundos o intentar entrar en los datos de tus clientes. 

Este middleware existe para:
1.  **Interceptar antes de Procesar:** Detiene cualquier petición maliciosa antes de que llegue a la lógica de negocio, ahorrando CPU, memoria y dinero.
2.  **Garantizar la Identidad:** Asegura que cada bit de información pertenezca a un `tenant` (cliente) válido.
3.  **Proteger la Infraestructura:** Actúa como un escudo contra ataques de fuerza bruta que intentarían saturar tu base de datos.

---

## 💎 ¿Por qué es la mejor solución posible? (God Tier)

No todos los sistemas de autenticación son iguales. Lo que hace que este sea "God Tier" es su **arquitectura de triple propósito**:

### 1. Inteligencia en la Puerta (Static Prefix Whitelist)
La mayoría de los sistemas usan listas fijas de rutas permitidas. Nosotros usamos **Prefix Matching**.
*   **Por qué es mejor:** Permite que el sistema crezca solo. Si mañana añades 100 páginas de documentación técnica bajo `/docs/v2/`, el sistema las protege o libera automáticamente sin que tengas que tocar una sola línea de código de seguridad. Es **escalabilidad infinita**.

### 2. Memoria Selectiva (IP Brute Force)
No solo validamos llaves, vigilamos el comportamiento. Usamos **Redis** para recordar quién está fallando.
*   **Por qué es mejor:** Si una IP intenta 5 veces entrar con llaves falsas, el sistema la "borra del mapa" temporalmente. Esto protege tu Base de Datos de ataques inquisitivos y mantiene tu sistema disponible para los usuarios reales. Es **autodefensa activa**.

### 3. El Sello de Calidad (Request State Injection)
Este es el secreto de la velocidad de AgentShield. Una vez que el middleware confirma quién eres, te pone un "sello invisible" en la petición.
*   **Por qué es mejor:** Normalmente, cada vez que una petición pasa por diferentes capas (pagos, auditoría, IA), el sistema tiene que volver a preguntar: "¿Quién es este?". Aquí, el middleware lo resuelve una vez y lo "inyecta" en `request.state.tenant_id`. Todo el resto de la aplicación es **mucho más rápida** porque ya confía en el veredicto del middleware.

---

## 📄 El Código de Elite (`app/middleware/auth.py`)

```python
import logging
from fastapi import HTTPException, Request
from app.config import settings
from app.db import redis_client
from app.limiter import get_real_ip_address
from app.logic import verify_api_key

logger = logging.getLogger("agentshield.auth")

async def global_security_guard(request: Request):
    # --- NIVEL 1: EL FILTRO DINÁMICO ---
    path = request.url.path
    if any(path.startswith(prefix) for prefix in settings.AUTH_WHITELIST):
        return

    if request.method == "OPTIONS":
        return

    # --- NIVEL 2: EL ESCUDO ANTI-ATAQUE ---
    client_ip = get_real_ip_address(request)
    block_key = f"auth_block:{client_ip}"
    
    if await redis_client.get(block_key):
        logger.warning(f"🛑 Acceso denegado a {client_ip} (Bloqueo preventivo)")
        raise HTTPException(429, "Demasiados intentos. Por favor, espera unos minutos.")

    # --- NIVEL 3: VALIDACIÓN E INYECCIÓN DE ALTA VELOCIDAD ---
    try:
        tenant_id = await verify_api_key(request.headers.get("Authorization"))
        
        # Inyectamos el ID para eliminar redundancia en los routers
        request.state.tenant_id = tenant_id
        
        # Limpieza de historial para usuarios legítimos
        await redis_client.delete(f"auth_fail:{client_ip}")
        
    except HTTPException as e:
        # Lógica de detección de intrusos
        fail_key = f"auth_fail:{client_ip}"
        fails = await redis_client.incr(fail_key)
        
        if fails == 1:
            await redis_client.expire(fail_key, settings.AUTH_BRUTE_FORCE_WINDOW)
            
        if fails >= settings.AUTH_BRUTE_FORCE_LIMIT:
            await redis_client.setex(block_key, settings.AUTH_BRUTE_FORCE_WINDOW, "blocked")
            logger.error(f"🚨 IP bloqueada: {client_ip} (Límite de fallos alcanzado)")
            
        raise e
```

---

## 📈 Impacto en el Negocio
Con este archivo, AgentShield no solo es más seguro, es **más barato de mantener** y **más rápido para el cliente final**. Es la diferencia entre una puerta de madera con una llave vieja y un sistema de control de acceso biométrico que te reconoce antes de llegar a la puerta.
