 # 🌐 app/routers — Visión General (God Tier)
 
 Esta sección describe la **capa HTTP** de AgentShield: qué routers existen, qué dominios cubren, y cómo conectan con los servicios internos.
 
 ---
 
 ## ✅ Lista completa de routers (23)
 
 ```
 admin_chat.py
 admin_roles.py
 ai_act_compliance.py
 analytics.py
 audit.py
 authorize.py
 budget_management.py
 compliance.py
 dashboard.py
 embeddings.py
 feedback.py
 forensics.py
 images.py
 invoices.py
 onboarding.py
 pii_config.py
 proxy.py
 public_config.py
 receipt.py
 tools.py
 trust.py
 webhooks.py
 ```
 
 ---
 
 ## 🧭 Agrupación por dominio
 
 ### 1) Core IA / Ejecución
 - `proxy.py` → `/v1/chat/completions` (pipeline completo + streaming HUD)
 - `images.py` → `/v1/images/generations`
 - `embeddings.py` → `/v1/embeddings`
 
 ### 2) Finanzas y gasto
 - `authorize.py` → `/v1/authorize` (pre‑autorización)
 - `receipt.py` → `/v1/receipt` y `/v1/evidence/package`
 - `invoices.py` → facturación
 - `budget_management.py` → budgets, wallets, anomalías
 
 ### 3) Compliance y auditoría
 - `compliance.py` → GDPR + cuarentena
 - `audit.py` → claves públicas y auditoría criptográfica
 - `forensics.py` → replay forense
 - `ai_act_compliance.py` → EU AI Act (clasificación, aprobaciones)
 
 ### 4) Admin y políticas
 - `dashboard.py` → métricas, reportes, costos
 - `tools.py` → gobernanza de herramientas
 - `admin_chat.py` → copilot de políticas
 - `admin_roles.py` → generación de roles
 
 ### 5) Trust y feedback
 - `trust.py` → ajuste de trust score
 - `feedback.py` → feedback y aprendizaje
 
 ### 6) Config pública y PII
 - `public_config.py` → config pública por tenant
 - `pii_config.py` → patrones PII dinámicos
 
 ### 7) Onboarding y webhooks
 - `onboarding.py` → signup, orgs, invitaciones
 - `webhooks.py` → triggers internos
 
 ---
 
 ## 🔗 Cómo se conectan con services/
 
 Cada router **orquesta** y delega en `app/services/*`. Ejemplos clave:
 
 - `proxy.py` → `DecisionPipeline`, `LLM Gateway`, `Receipt Manager`, `PII Guard`, `Trust System`
 - `authorize.py` → `cost_estimator`, `policy engine`, `budget limiter`
 - `receipt.py` → `billing` + `crypto_signer`
 - `compliance.py` → `compliance_reporter` + `file_guardian`
 - `ai_act_compliance.py` → `eu_ai_act_classifier` + `human_approval_queue`
 - `dashboard.py` → `pricing_sync`, `analytics`, `supabase` RPCs
 
 ---
 
 ## ✅ Principios de la capa Router
 
 - **No ejecuta lógica pesada**: delega a services.
 - **Recibe requests ya filtrados** por `middleware/` (auth + security).
 - **Usa `tenant_id` en `request.state`** como contexto base.
 - **Cada endpoint** mantiene trazabilidad con `trace_id`.
 
 ---
 
 ## 🧪 Endpoints críticos (mapa rápido)
 
 - `/v1/chat/completions` → core product
 - `/v1/authorize` → gobernanza previa
 - `/v1/receipt` → auditoría legal
 - `/v1/dashboard/*` → control administrativo
 - `/v1/compliance/*` + `/ai-act/*` → cumplimiento
 
