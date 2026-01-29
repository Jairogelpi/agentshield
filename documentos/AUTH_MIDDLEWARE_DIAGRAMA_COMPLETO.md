 # 🛡️ Auth Middleware (God Tier) — Diagrama + Explicacion Extrema
 
 Este documento esta pensado para un programador senior revisando el sistema completo. No omite nada del flujo real de `app/middleware/auth.py` ni de sus efectos en el resto del proyecto.
 
 ---
 
 ## ✅ Diagrama Mermaid (Seguro, sin errores)
 
 ```mermaid
 flowchart TD
     A["Inicio Auth"] --> B["Telemetria\npath, trace_id, client_ip"]
     B --> C{"Whitelist por prefijo?\nAUTH_WHITELIST"}
     C -- "Si" --> Z["Permitir request"]
     C -- "No" --> D{"OPTIONS?"}
     D -- "Si" --> Z
     D -- "No" --> E["Brute Force Check\nredis auth_block:<ip>"]
 
     E -- "Blocked" --> F["SIEM INFO\nAUTH_BRUTE_FORCE_BLOCKED\ntrace_id + ip"]
     F --> G["HTTP 429\nToo many failed attempts"]
 
     E -- "Redis error" --> H["Log error\nContinuar por disponibilidad"]
     H --> I["verify_api_key(Authorization)"]
 
     E -- "Not blocked" --> I["verify_api_key(Authorization)"]
 
     I -- "Success" --> J["Set tenant_id\nrequest.state.tenant_id"]
     J --> K["Cleanup\nredis delete auth_fail:<ip>"]
     K --> Z
 
     I -- "HTTPException" --> L["Fail counter\nredis incr auth_fail:<ip>"]
     L --> M["Set expire\nAUTH_BRUTE_FORCE_WINDOW"]
     M --> N["SIEM WARNING\nAUTH_FAILURE\nfails_count"]
     N --> O{"fails >= LIMIT?"}
     O -- "Si" --> P["Set block\nredis setex auth_block:<ip>"]
     P --> Q["SIEM CRITICAL\nAUTH_BRUTE_FORCE_LIMIT_REACHED"]
     Q --> R["Reraise HTTPException"]
     O -- "No" --> R
 
     L -- "Redis error" --> S["Log error\nContinuar"]
     S --> R
 ```
 
 ---
 
 ## 🧠 Explicacion Completa (bloque por bloque)
 
 ### 1) Telemetria inicial
 - **Variables:** `path`, `trace_id`, `client_ip`.
 - `trace_id` viene del middleware de seguridad si ya corrio; si no, usa `TRC-UNKNOWN`.
 - `client_ip` usa `get_real_ip_address(request)` (toma IP real, no la del proxy).
 
 **Impacto:** alimenta logs, SIEM y permite debugging forense. Este `trace_id` vincula toda la ejecucion.
 
 ---
 
 ### 2) Whitelist por prefijo
 - Se compara `path.startswith(prefix)` contra `settings.AUTH_WHITELIST`.
 - **Si coincide, se retorna sin validar credenciales.**
 
 **Por que es God Tier:**  
 el whitelist es **dinamico por prefijo**, no lista fija. Si mañana se agregan rutas nuevas bajo un prefijo, quedan cubiertas sin tocar seguridad.
 
 **Impacto:** evita overhead en endpoints publicos (docs, health, assets, etc.).
 
 ---
 
 ### 3) Bypass para OPTIONS
 - Si el metodo es `OPTIONS`, retorna sin auth.
 
 **Impacto:** garantiza CORS preflight correcto. Sin esto, navegadores bloquean llamadas legitimas.
 
 ---
 
 ### 4) Brute Force Check (Pre-auth)
 - Se arma `block_key = auth_block:<ip>`.
 - Si Redis tiene ese key:
   - Log warning.
  - Publica evento SIEM `AUTH_BRUTE_FORCE_BLOCKED` con `tenant_id="SYSTEM"` y `severity="INFO"`.
   - Responde `HTTP 429`.
 
 **Impacto:** corta ataques antes de consumir CPU en verificacion de token. Protege presupuesto y disponibilidad.
 
 ---
 
 ### 5) Fallback si Redis falla
 - Cualquier error de Redis en el pre-check se loguea.
 - **El sistema deja pasar el request** (prioriza disponibilidad).
 
 **Impacto:** si Redis cae, no se caen todos los endpoints privados. Se sacrifica proteccion anti brute force temporalmente.
 
 ---
 
 ### 6) Validacion de credenciales
 - `verify_api_key(request.headers.get("Authorization"))`.
 - Si es valido, retorna `tenant_id`.
 - Se inyecta: `request.state.tenant_id = tenant_id`.
 - Si falla, se captura `HTTPException` y se re-lanza al final del flujo.
 
 **Impacto:** todo el resto del sistema depende de `tenant_id` para aislar datos y costos por cliente.
 
 ---
 
 ### 7) Limpieza de fallos
 - Si auth fue exitosa: `redis delete auth_fail:<ip>`.
 - Si el delete falla, el error se ignora (try/except pass).
 
 **Impacto:** evita castigar a usuarios legitimos que se equivocaron antes.
 
 ---
 
 ### 8) Manejo de fallo de auth
 - Si `verify_api_key` lanza `HTTPException`:
   - Incrementa `auth_fail:<ip>`.
  - Si es primer fallo (`fails == 1`), expira en `AUTH_BRUTE_FORCE_WINDOW`.
  - Publica SIEM `AUTH_FAILURE` con `tenant_id="SYSTEM"` y `severity="WARNING"`, incluye `fails_count`.
 
 **Impacto:** se instrumenta seguridad activa y estadistica de ataques.
 
 ---
 
 ### 9) Bloqueo por limite
 - Si `fails >= AUTH_BRUTE_FORCE_LIMIT`:
   - `redis setex auth_block:<ip>` con ventana configurada.
   - Log error.
  - SIEM `AUTH_BRUTE_FORCE_LIMIT_REACHED` con `tenant_id="SYSTEM"` y `severity="CRITICAL"`.
 
 **Impacto:** corta el ataque y activa playbooks de seguridad automatizados.
 
 ---
 
 ### 10) Fallback si Redis falla en el contador
 - Se loguea error.
 - Se re-lanza la excepcion original.
 
 **Impacto:** el usuario recibe error consistente aunque el contador no se haya actualizado.
 
 ---
 
 ## 🔗 Dependencias directas
 - `settings.AUTH_WHITELIST`
 - `settings.AUTH_BRUTE_FORCE_LIMIT`
 - `settings.AUTH_BRUTE_FORCE_WINDOW`
 - `redis_client`
 - `verify_api_key`
 - `event_bus`
 - `get_real_ip_address`
 
 ---
 
 ## ✅ Impacto en el resto del proyecto (macro)
 
 - **Aislamiento multi-tenant:** `tenant_id` queda en `request.state` para routers y servicios.
 - **Proteccion de presupuesto:** evita costo por requests maliciosos.
 - **Observabilidad:** SIEM recibe eventos en tiempo real.
 - **Disponibilidad:** si Redis falla, el sistema sigue operando.
 - **Latencia:** whitelist reduce overhead en rutas publicas.
 
