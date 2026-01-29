 # 🧠 app/ — Esquema Global God Tier
 
 Este documento describe **todo el subsistema `app/`** con precision senior: estructura, responsabilidades, flujos criticos y dependencias reales. Esta pensado para lectura tecnica profunda y para construir diagramas de arquitectura o auditoria.
 
 ---
 
 ## ✅ Diagrama Mermaid (Seguro, sin errores)
 
 ```mermaid
 flowchart TD
     A["Entrada HTTP\nClientes / OpenWebUI / MCP"] --> B["main.py\nFastAPI App"]
     B --> C["Middleware\nsecurity_guard_middleware\n+ global_security_guard"]
     C --> D["Routers\napp/routers/*"]
     D --> E["Services\napp/services/*"]
 
     E --> F["Data Layer\nSupabase + Redis"]
     E --> G["LLM Gateway\nLiteLLM + Vendors"]
     E --> H["Observabilidad\nEvent Bus + Logs + trace_id"]
     E --> I["Rust Module\nPII + Entropy + C2PA"]
 
     J["workers/\nBackground Jobs"] --> F
 ```
 
 ---
 
 ## 1) Mapa estructural completo
 
 ```
 app/
 ├── main.py              # Punto de entrada FastAPI
 ├── config.py            # Configuracion central
 ├── db.py                # Redis + Supabase + WAL
 ├── schema.py            # DecisionContext
 ├── models.py            # Modelos Pydantic
 ├── logic.py             # Logica compartida (auth, policies, tokens)
├── http_limiter.py      # Rate limiting HTTP (SlowAPI)
├── cost_estimator.py    # Estimacion de costos (multimodal)
 ├── decorators.py        # Decoradores (semantic_cache)
 ├── middleware/          # Seguridad (auth + security)
 ├── routers/             # Endpoints HTTP (23 routers)
 ├── services/            # Logica real (50+ servicios)
 ├── workers/             # Jobs background
 └── utils/               # Utilidades
 ```
 
 ---
 
 ## 2) main.py — Arranque, wiring y salud del sistema
 
 **Responsabilidad:** crear la app FastAPI, registrar middlewares, routers, monitoreo y health.
 
 **Flujo de arranque real:**
 - `recover_pending_charges()` (WAL recovery)
 - `init_semantic_cache_index()`
 - `update_market_rules()`
 - `sync_universal_prices()`
 - Warmup de modelos locales (`pii_guard` y `reranker`)
 
 **Health check:**
 - `/health` simple (warming_up vs ok)
 - `/health?full=true` valida Redis + Supabase
 
 **Impacto:** determina readiness real del sistema y evita servir trafico si modelos no estan listos.
 
 ---
 
 ## 3) config.py — Configuracion central
 
 **Responsabilidad:** parametros globales de seguridad, integraciones y limites:
 - Secrets (JWT, Cloudflare proxy secret)
 - Redis / Supabase endpoints
 - Whitelist de rutas publicas
 - Limites de brute force
 - Parametros de budget y seguridad
 
 **Impacto:** cambia el comportamiento del core sin tocar codigo.
 
 ---
 
 ## 4) db.py — Persistencia + hot path financiero
 
 **Responsabilidad:** acceso a Redis y Supabase, con logica de recuperación.
 
 **Funciones criticas:**
 - `increment_spend()`:
   - Actualiza Redis (hot path)
   - Guarda en WAL (seguridad)
   - Persiste asincrono a Supabase
 - `get_current_spend()`:
   - Lee de Redis con fallback a DB
 - `recover_pending_charges()`:
   - Reprocesa WAL despues de crash
 
 **Impacto:** protege contabilidad y garantiza consistencia post-crash.
 
 ---
 
## 5) middleware/ — Seguridad de borde
 
 **auth.py** (`global_security_guard`)
 - Valida API Key / JWT
 - Brute force guard con Redis
 - Inyecta `tenant_id`
 - Publica eventos SIEM
 
 **security.py** (`security_guard_middleware`)
 - Valida Cloudflare secret (si esta configurado)
 - Genera `trace_id`
 - Aplica headers de seguridad
 - Mide latencia inicial
 
 **Orden efectivo:**
 1) `global_security_guard` (Depends global)
 2) `security_guard_middleware` (middleware HTTP)
 
**Impacto:** todo request llega a routers ya autenticado y con `trace_id`.
 
 ---
 
## 6) routers/ — Capa HTTP (orquestacion)
 
 Esta capa define el contrato externo. Cada router delega en servicios.
 
 **Grupos funcionales:**
 - **Ejecucion IA:** `proxy`, `images`, `embeddings`
 - **Finanzas:** `authorize`, `receipt`, `invoices`, `budget_management`
 - **Compliance:** `compliance`, `audit`, `forensics`, `ai_act_compliance`
 - **Admin:** `dashboard`, `admin_roles`, `admin_chat`, `tools`
 - **Confianza:** `trust`
 - **Config:** `public_config`, `pii_config`
 - **Feedback/Webhooks:** `feedback`, `webhooks`
 
 **Impacto:** es el mapa de superficie publica del sistema.
 
 ---
 
## 7) services/ — Lógica real (core del negocio)
 
Servicios clave y sus roles:
 
 - **DecisionPipeline**: orquesta gates (intent, trust, PII, budget, arbitrage).
 - **PII Guard**: detecta y redacta datos sensibles (usa Rust).
 - **Trust System**: score dinamico y enforcement de politicas.
- **Billing / Receipt Manager**: recibos forenses + firma.
- **Market Pricing**: `services/market_pricing.py` (precios reales por modelo).
- **Budget Limiter**: `services/budget_limiter.py` (wallets y velocity).
 - **LLM Gateway**: llamadas resilientes a proveedores.
 - **Hive Mind**: cache federado y memoria corporativa.
 - **Event Bus**: eventos SIEM y auditoria.
 
 **Impacto:** aqui se decide el modelo final, el costo real, y la evidencia de auditoria.
 
 ---
 
 ## 8) schema.py — DecisionContext (estado global)
 
 **Responsabilidad:** encapsular el estado de una peticion durante el pipeline.
 
 Campos tipicos:
 - Identidad (`tenant_id`, `user_id`)
 - Riesgo (`trust_score`, `risk_mode`)
 - Compliance (`pii_redacted`)
 - Modelo (`requested_model`, `effective_model`)
 - Auditoria (`decision_log`)
 
 **Impacto:** permite un pipeline reproducible y auditable.
 
 ---
 
 ## 9) logic.py — Lógica compartida
 
 **Responsabilidad:** funciones comunes reutilizadas por routers y servicios.
 Ejemplos: validacion de API Keys, tokens de autorizacion, politicas activas.
 
 **Impacto:** evita duplicacion de reglas criticas.
 
 ---
 
 ## 10) workers/ — Background jobs
 
 - `trust_healer.py`: recupera trust score de usuarios despues de periodos sanos.
 
 **Impacto:** correccion automatica de scores sin intervencion humana.
 
 ---
 
 ## 11) Flujos criticos (alto nivel)
 
 **A) Request de chat principal**
 1) Middlewares (auth + security)
 2) `proxy.py` recibe request
 3) `DecisionPipeline.process_request()`
 4) `LLM Gateway` ejecuta
 5) `Receipt Manager` genera recibo
 6) `increment_spend()` y eventos SIEM
 
 **B) Autorizacion previa**
 1) `/v1/authorize` valida budget y policy
 2) Genera token AUT
 3) Token se usa en ejecucion real
 
 **C) Recuperacion financiera**
 1) WAL en Redis
 2) worker persiste a Supabase
 3) recovery en startup
 
 ---
 
 ## 12) Dependencias criticas (resumen)
 - `middleware/` antes de cualquier router
 - `DecisionPipeline` como orquestador central
 - Redis como hot path financiero
 - Supabase como persistencia definitiva
 - Rust module para PII y C2PA
 
