 # 🛡️ Security Middleware (God Tier) — Diagrama + Explicacion Extrema
 
 Este documento esta pensado para un programador senior revisando el sistema completo. No omite nada del flujo real de `app/middleware/security.py` ni de sus efectos en el resto del proyecto.
 
 ---
 
 ## ✅ Diagrama Mermaid (Seguro, sin errores)
 
 ```mermaid
 flowchart TD
     A["Inicio de request"] --> B["Start TS\nrequest.state.start_ts = time.time()\n(telemetria HUD/latencia)"]
     B --> C{"Bypass?\n/health OR OPTIONS OR ENV=development"}
     C -- "Si" --> Z["call_next(request)\nSin validacion extra"]
     C -- "No" --> D["Trace ID\nX-Request-ID o UUID\nrequest.state.trace_id"]
     D --> E{"Cloudflare Check\nX-AgentShield-Auth == CLOUDFLARE_PROXY_SECRET"}
     E -- "No" --> F["403 JSONResponse\nSecurity Breach\nIncluye trace_id\nLog warning + IP real"]
     E -- "Si" --> G["call_next(request)\nProcesa app"]
     G --> H["Headers de seguridad\nHSTS 2 anios + preload\nX-Frame-Options: DENY\nX-Content-Type-Options: nosniff\nX-XSS-Protection: 1; mode=block\nX-Request-ID\nX-AgentShield-Region"]
 ```
 
 ---
 
 ## 🧠 Explicacion Completa (bloque por bloque)
 
 ### 1) Telemetria inicial (Zenith Anchor)
 - Se guarda `request.state.start_ts = time.time()`.
 - Este valor es el ancla para medir latencia end-to-end en HUD/dashboards.
 
 **Impacto:** sin este timestamp, no hay medicion real de performance de peticiones.
 
 ---
 
 ### 2) Bypass controlado
 - Si path es `/health`, si metodo es `OPTIONS`, o si `ENVIRONMENT == development`:
   - El middleware **no aplica seguridad** y retorna `call_next`.
 
 **Impacto:** evita latencias y friccion en health checks y en desarrollo local.
 
 ---
 
 ### 3) Identidad del request (Trace ID)
 - Toma `X-Request-ID` si existe.
 - Si no existe, crea UUID nuevo.
 - Guarda en `request.state.trace_id`.
 
 **Impacto:** este `trace_id` es la llave forense que luego usan auth, logs, SIEM y respuestas de error.
 
 ---
 
 ### 4) Verificacion Cloudflare (Candado)
 - Usa `settings.CLOUDFLARE_PROXY_SECRET`.
 - Compara contra `X-AgentShield-Auth`.
 - Si no coincide: se bloquea.
 - Si `CLOUDFLARE_PROXY_SECRET` esta vacio o no configurado, **no se aplica el check** (pasa directo).
 
 **Impacto:** hace el backend **invisible** para accesos directos a IP. Solo Cloudflare puede entrar.
 
 ---
 
 ### 5) Respuesta forense
 - Si falla el check:
   - Status 403.
   - JSON con `error`, `message`, `trace_id`.
  - Log warning con IP real usando `cf-connecting-ip` o fallback a `request.client.host`.
 
 **Impacto:** respuesta auditable y rastreable por seguridad.
 
 ---
 
 ### 6) Procesamiento normal
 - Si el request pasa el candado, se ejecuta `call_next`.
 
 **Impacto:** solo trafico valido entra al resto del sistema.
 
 ---
 
 ### 7) Blindaje de headers (Zenith Header Protocol 2026)
 Headers aplicados SIEMPRE:
 - `Strict-Transport-Security` (2 anios, includeSubDomains, preload)
 - `X-Frame-Options: DENY`
 - `X-Content-Type-Options: nosniff`
 - `X-XSS-Protection: 1; mode=block`
 - `X-Request-ID` (trace id)
 - `X-AgentShield-Region`
 
 **Impacto:** cumplimiento SOC2/ISO y proteccion activa contra ataques web.
 
 ---
 
 ## 🔗 Dependencias directas
 - `settings.ENVIRONMENT`
 - `settings.CLOUDFLARE_PROXY_SECRET`
 - `os.getenv("SERVER_REGION")`
 - `JSONResponse`
 
 ---
 
 ## ✅ Impacto en el resto del proyecto (macro)
 
 - **Protege todo el backend** antes de routers y servicios.
 - **Define el trace_id** que otros componentes reutilizan.
 - **Evita ataques directos** a la IP o instancia.
 - **Cumple estandares legales** y de seguridad web.
 - **Aporta observabilidad real** con latencias medibles.
 
