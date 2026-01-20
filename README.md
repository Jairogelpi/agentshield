# 🛡️ AgentShield OS (Enterprise Core)

[![CI](https://github.com/Jairogelpi/agentshield/actions/workflows/ci.yml/badge.svg)](https://github.com/Jairogelpi/agentshield/actions/workflows/ci.yml)

> **El Sistema Operativo de Confianza y Gasto para IA Empresarial**
>
> Una plataforma "God Tier" que transforma la adopción de IA corporativa: de un riesgo incontrolable a un activo auditado, presupuestado y optimizado.

---

## 🚀 La Propuesta de Valor (One Sentence Architecture)
Una plataforma web (Chat + API) donde **cada interacción con IA genera un "recibo" forense firmado**, verificable y aplicable (Policy-Proof), con identidad corporativa federada, presupuestos jerárquicos (Waterfall), DLP/PII en tiempo real, enrutamiento multi-modelo y contabilidad granular, sin instalación para el cliente.

---

## 💎 La Jugada Revolucionaria: "Receipts + Policy-Proofs"

Tu diferenciación no es el chat, es la **Evidencia**.

### 1. El Recibo Forense (Tamper-Evident)
Cada request genera un objeto JSON inmutable, firmado criptográficamente y encadenado al anterior (Blockchain-Lite):
*   `user_hash` & `context_id` (Identidad)
*   `policy_decision` & `policy_version` (Gobernanza)
*   `tokens`, `latency`, `cost_usd` (Auditoría Financiera)
*   **Signature**: RSA-SHA256 del contenido.
*   **Chain**: `prev_hash` garantiza que nadie borró logs intermedios.

### 2. Policy-Proof (La Prueba de Cumplimiento)
No solo bloqueamos, **probamos la decisión**:
> "Regla aplicada: `PII.CC_NUMBERS_BLOCK@v12`. Razón: Patrón detectado con score 0.98. Remediación: Redacción automática."

Esto cambia la conversación de "Confía en mí" a "**Aquí está la prueba matemática**".

---

## 🏛️ Arquitectura: Tres Caras, Un Cerebro

El sistema se despliega como un SaaS completo (Zero Install):

### A. La Cara del Empleado: "AgentShield Chat"
*   **Tecnología**: OpenWebUI (Marca Blanca) / LibreChat.
*   **Experiencia**: Como ChatGPT, pero seguro.
*   **Features**: SSO Corporativo, Modelos Virtuales ("AgentShield Smart/Fast"), Indicadores de Privacidad.

### B. El Cerebro: "AgentShield Core" (Backend)
*   **Tecnología**: Python (FastAPI + Granian) en Render.
*   **Funciones**:
    *   **Universal Proxy**: API compatible con OpenAI (`/v1/chat/completions`).
    *   **Neural Hive**: Memoria corporativa compartida (RAG colaborativo).
    *   **PII Guard**: Redacción de datos sensibles en tiempo real (Rust/ONNX).
    *   **Budget Negotiator**: El "AI CFO" que aprueba/deniega gastos extra.

### C. El Control: "AgentShield Dashboard" (Frontend)
*   **Tecnología**: Next.js (Vercel) + Supabase.
*   **Vistas**:
    *   **Security View**: Políticas "Shadow Mode" (simulación) y Enforce.
    *   **Legal View**: Verificación forense de recibos (RSA Check).
    *   **Money View**: ROI, Arbitraje y Ahorro por Caché.
    *   **Hive View**: Visualización 3D del conocimiento corporativo.

---

## 📚 Documentación Técnica (Deep Dives)

*   [**0. Master Plan**](documentation/00_MASTER_PLAN.md)
*   [**1. Infraestructura**](documentation/01_INFRAESTRUCTURA.md)
*   [**2. Seguridad Zero Trust**](documentation/02_SEGURIDAD.md)
*   [**3. Motor Financiero**](documentation/03_FINANCIERO.md)
*   [**4. Proxy Router**](documentation/04_PROXY.md)
*   [**6. Estrategia Frontend**](documentation/06_FRONTEND_STRATEGY.md)
*   [**7. Secure RAG Vault**](documentation/07_SECURE_RAG_VAULT.md)
*   [**8. Evolutionary AI**](documentation/08_EVOLUTIONARY_AI.md)

---

## 🛠️ Stack Tecnológico
*   **Core**: Python 3.11+, FastAPI, Granian (Rust Server).
*   **Auth**: JWT (Identity Envelopes) + Supabase Auth.
*   **Data**: Supabase (PostgreSQL + pgvector).
*   **Memory**: Redis (Semantic Cache & Rate Limit).
*   **AI Gateway**: LiteLLM (Unified Interface).
*   **Frontend**: Next.js 14, Tailwind, Shadcn/UI, Tremor.

> **Versión**: 2.0.0 ("God Tier")
