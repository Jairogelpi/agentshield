# 🛡️ El Escudo Invisible (Security Middleware: God Tier Sensor)

Si el archivo de autenticación (`auth.py`) es el **Portero Inteligente**, este archivo (`security.py`) es la **Cerca Eléctrica Sensorial** de AgentShield. No solo protege, sino que "siente" los ataques antes de que lleguen a la puerta.

---

## 1. ¿Qué hace este archivo?
Su misión es asegurar que **nadie** pueda ver el edificio ni tocar la puerta si no viene por el camino oficial (Cloudflare). Es lo que hace que AgentShield sea invisible para los atacantes que escanean Internet buscando servidores débiles.

## 2. Los 3 Pilares del Escudo

### No. 1: El Túnel Privado (Cloudflare Verification)
Imagina que hay una carretera secreta que lleva al edificio. Este código verifica que cada coche que llega trae un "pase especial" (`X-AgentShield-Auth`).
*   **¿Cómo funciona?:** Si intentas llegar al edificio por el campo o por otra carretera (acceso directo a la IP), el escudo detecta que no tienes el pase y te bloquea al instante.
*   **Por qué es perfecto:** Evita que hackers ataquen directamente tu servidor en Render o AWS. Si no pasan por el filtro de Cloudflare, simplemente no existen para nosotros.

### No. 2: El Blindaje de Comunicación (HSTS Zenith)
Una vez que estás dentro, nos aseguramos de que nadie pueda interceptar la comunicación.
*   **La magia:** Activamos `Strict-Transport-Security` con un `max-age` de 2 años, subdominios y pre-carga.
*   **Soberanía de Datos:** Inyectamos `X-AgentShield-Region` en cada respuesta para certificar dónde están siendo procesados los datos.

### No. 3: Sensor de Red (The Trace Anchor & SIEM)
Convertimos cada bloqueo en inteligencia de amenazas.
*   **La magia:** Al interceptar un acceso no autorizado por Cloudflare, el sistema no solo bloquea; emite una señal de severidad `WARNING` o `CRITICAL` al SIEM.
*   **Por qué es perfecto:** Permite al CISO ver intentos de bypass de la red perimetral. Cada evento lleva el `trace_id` original, permitiendo una trazabilidad total desde el primer cable hasta la última respuesta de la IA.

---

## 3. Cabeceras Enterprise 2026
AgentShield implementa el estándar completo:
- `X-Frame-Options: DENY` (Anti-Clickjacking)
- `X-Content-Type-Options: nosniff` (Anti-MIME Sniffing)
- `X-XSS-Protection: 1; mode=block` (Protección activa de navegador)
- `X-Request-ID`: Propagación de identidad de red.

---

## 4. ¿Por qué lo necesitamos?
Sin este escudo, AgentShield estaría expuesto como una casa en medio de un descampado. Con este middleware, la infraestructura es invisible y solo los agentes y usuarios autorizados conocen el camino.

---

## 5. ¿Cómo afecta al resto del programa?
Este archivo trabaja en las "sombras", antes de que el programa siquiera empiece a pensar en IA:
*   **Tranquilidad Total:** Los desarrolladores saben que si la petición llega a su código, ya pasó por el filtro de Cloudflare y es segura.
*   **Cumplimiento Legal:** Cumple con normativas de seguridad (ISO 27001 / SOC2) al forzar comunicaciones seguras y prevenir ataques web comunes.
