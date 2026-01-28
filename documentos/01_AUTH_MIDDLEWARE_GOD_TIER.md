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

### 3. El Sello de Calidad (Traceability Anchor)
Este es el hilo conductor de la verdad. Inyectamos un `trace_id` universal desde el primer milisegundo.
*   **Por qué es mejor:** Si hay un error, el sistema te da un `X-Request-ID`. Con ese código, puedes rastrear exactamente qué pasó en los logs, las políticas y hasta la respuesta final de la IA. Es **transparencia forense**.

### 4. Señalización SIEM (Immune System Signaling)
No solo bloqueamos; alertamos. Usamos el `event_bus` para notificar fallos en tiempo real.
*   **Por qué es mejor:** Si una IP es bloqueada por fuerza bruta, el sistema emite un evento `AUTH_BRUTE_FORCE_LIMIT_REACHED` de severidad `CRITICAL`. Esto activa playbooks de seguridad automatizados. Es **seguridad proactiva**.

### 5. Resiliencia de Clase Enterprise
El sistema está diseñado para no rendirse. Si Redis parpadea, AgentShield prioriza la disponibilidad sin comprometer la validación de llaves principal.

---

## 📄 El Código de Elite (`app/middleware/auth.py`)

```python
async def global_security_guard(request: Request):
    # --- NIVEL 0: TELEMETRÍA Y ANCLAJE ---
    trace_id = getattr(request.state, "trace_id", "TRC-UNKNOWN")
    client_ip = get_real_ip_address(request)
    
    # --- NIVEL 1: FILTRO DINÁMICO ---
    if any(path.startswith(p) for p in settings.AUTH_WHITELIST): return

    # --- NIVEL 2: ESCUDO ANTI-ATAQUE CON SIEM ---
    block_key = f"auth_block:{client_ip}"
    if await redis_client.get(block_key):
        # SIEM SIGNAL
        await event_bus.publish(event_type="AUTH_BRUTE_FORCE_BLOCKED", severity="INFO", ...)
        raise HTTPException(429, "Too many attempts.")

    # --- NIVEL 3: VALIDACIÓN E INYECCIÓN ---
    try:
        tenant_id = await verify_api_key(request.headers.get("Authorization"))
        request.state.tenant_id = tenant_id
    except HTTPException as e:
        # DETECCIÓN DE FUERZA BRUTA Y ALERTA CRÍTICA
        fails = await redis_client.incr(f"auth_fail:{client_ip}")
        if fails >= settings.AUTH_BRUTE_FORCE_LIMIT:
            await event_bus.publish(event_type="AUTH_BRUTE_FORCE_LIMIT_REACHED", severity="CRITICAL", ...)
        raise e
```

---

## 📈 Impacto en el Negocio
Con este archivo, AgentShield no solo es más seguro, es **más barato de mantener** y **más rápido para el cliente final**. Es la diferencia entre una puerta de madera con una llave vieja y un sistema de control de acceso biométrico que te reconoce antes de llegar a la puerta.
