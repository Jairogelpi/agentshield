# 06. Estrategia Frontend: AgentShield OS (Dual Interface)

> **Estado**: En Construcción Activa
> **Versión**: 2.0 ("God Tier" Update)

Para el usuario final, AgentShield no es solo una API, es un sistema operativo empresarial ("OS"). Nuestra estrategia de frontend es dual: separamos la experiencia de "Consumo" (Chat) de la experiencia de "Control" (Dashboard), conectándolas mediante una identidad federada.

## 1. La Cara del Empleado: "El Chat Inteligente" (OpenWebUI)
**Objetivo**: Eliminar fricción. Que parezca ChatGPT, pero con esteroides de seguridad.

Esta interfaz consume la API de AgentShield como si fuera OpenAI, pero recibe valor añadido en cada respuesta.

### Implementación Técnica
-   **Endpoint**: `https://api.tuempresa.com/v1/chat/completions` (AgentShield Proxy).
-   **Identidad**: SSO inyecta `Identity Envelope` (JWT). No hay gestión de API Keys.
-   **Modelos Virtuales**:
    -   `AgentShield Auto`: Router inteligente que decide entre modelos según complejidad.
    -   `AgentShield Secure`: Garantiza PII stripping y borrado de registros.
-   **In-Chat HUD**: El proxy añade metadatos al final del stream de texto: `[🛡️ Trust Score: 98 | 🌱 Save: 0.4g CO2 | 💰 Ahorro: $0.02]`
    -   **Nuevo**: Indicador "🐝 Hive Hit" cuando la respuesta viene de la memoria corporativa.

---

## 2. La Cara del Admin/Jefe: "El Tablero de Control" (Next.js Dashboard)
**Objetivo**: Evidencia, Auditoría y Finanzas. Convertir lo intangible (seguridad) en tangible (gráficos y reportes).

Ubicación: `agentshield_frontend/src/app/(dashboard)`

### A. Gobernanza y Políticas ("Security View")
**Ruta**: `src/app/(dashboard)/dashboard/policies/page.tsx`
**Estado**: ✅ Implementado (Fase 5 Completada - Magic Layer Activo)

#### Estrategia
Dar al CISO el poder de simular antes de bloquear ("Shadow Mode") y crear reglas con lenguaje natural ("Policy Copilot").

#### Detalles de Implementación
-   **Tablas**: `policies` y `policy_events` (Supabase).
-   **Visualización**:
    -   Switch "Shadow Mode" vs "Enforce".
    -   **Simulador de Impacto**: Caja de alerta amarilla mostrando cuántos usuarios *habrían* sido bloqueados en las últimas 24h.
    -   **Hook**: `usePolicies` conecta con DB para traer hits reales.

### B. Auditoría Forense ("Legal View")
**Ruta**: `src/app/(dashboard)/dashboard/receipts/page.tsx`
**Estado**: ✅ Implementado (Fase 4)

#### Estrategia
Proveer prueba matemática de inocencia y cumplimiento ("Digital Notary").

#### Detalles de Implementación
-   **Backend**: `GET /v1/audit/public-key` expone la clave pública RSA (PEM).
-   **Frontend**:
    -   Botón "Verify" en cada fila de tabla.
    -   **`VerificationModal`**: Valida firma RSA y encadenamiento de hash.

### C. Visualización Financiera ("Money View")
**Componente**: `src/components/charts/spending-chart.tsx`
**Estado**: 🏗️ En Diseño

#### Estrategia
Mostrar el ROI del "Negotiator" y el "Gateway".
-   **Métricas**:
    -   `Gasto Real` vs `Coste Estimado` (Arbitraje).
    -   `Presupuesto Salvado`: Dinero ahorrado por bloqueos de política o uso de caché (Hive).
    -   `Overdrafts Aprobados`: Cuántas veces el "AI CFO" (Negotiator) salvó una tarea crítica.

### D. Sostenibilidad ("ESG View")
**Ruta**: `src/app/(dashboard)/dashboard/sustainability/page.tsx`
**Estado**: 🟡 Conectado a Backend

#### Estrategia
Convertir la eficiencia computacional en métricas ESG.
-   **Backend**: `GET /v1/analytics/sustainability` (RPC `get_total_carbon`).
-   **Frontend**: "Árboles Plantados", Rating Energético.

### E. Economía de Conocimiento ("Neural Hive View")
**Componente**: `src/components/3d/market-scene.tsx`
**Estado**: 🏗️ Concepto

#### Estrategia
Visualizar el cerebro de la empresa.
-   Nodos brillantes = Departamentos.
-   Conexiones = "Hive Hits" (Marketing usando solución de Ingeniería).
-   Gamificación: "Top Contributors" (Empleados cuyas soluciones son más reusadas).

---

## Roadmap de Integración
1.  **Policies (Shadow Mode)**: ✅ Implementado (UI + Hooks).
2.  **Hive Metrics**: Añadir contador de "Hive Hits" al dashboard principal.
3.  **Negotiator Logs**: Mostrar historial de negociaciones en el perfil del usuario.

---

## 3. Infraestructura y Despliegue (The Cloud OS)
Para garantizar la soberanía de datos y la escalabilidad, desplegamos en una arquitectura de tres capas:

### A. Core / Backend (Render)
El "Cerebro" que procesa, firma y audita.
-   **Servicio**: Web Service (Python/Granian).
-   **Lógica**: Gateway, Cryptography, Neural Hive.
-   **Variables Críticas**: `OPENAI_API_KEY`, `SUPABASE_JWT_SECRET`, `PRIVATE_KEY_PEM`.

### B. Dashboard / Control Plane (Vercel)
La interfaz de gestión para el equipo de seguridad y finanzas.
-   **Framework**: Next.js Edge Network.
-   **Conexión**: Consume la API de Render vía `NEXT_PUBLIC_API_URL`.

### C. Data Sovereignty (Supabase)
El "Vault" donde reside la evidencia legal y los vectores.
-   **Tablas**: `receipts` (Evidencia), `hive_memory` (Vectores), `policies` (Reglas).
-   **Vector DB**: pgvector activado para búsqueda semántica.
