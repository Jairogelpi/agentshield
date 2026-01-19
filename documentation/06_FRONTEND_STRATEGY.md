# 06. Estrategia Frontend: AgentShield OS (Dual Interface)

> **Estado**: En Construcción Activa
> **Versión**: 1.1 (Technical Blueprint)

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

---

## 2. La Cara del Admin/Jefe: "El Tablero de Control" (Next.js Dashboard)
**Objetivo**: Evidencia, Auditoría y Finanzas. Convertir lo intangible (seguridad) en tangible (gráficos y reportes).

Ubicación: `agentshield_frontend/src/app/(dashboard)`

### A. Visualización Financiera ("Money View")
**Componente**: `src/components/charts/spending-chart.tsx`
**Estado**: 🏗️ En Diseño

#### Estrategia
Mostrar no solo cuánto se gasta, sino cuánto **se ha dejado de gastar** gracias al arbitraje de IA.
-   **Query**: Endpoint `/v1/analytics/spending` (Pendiente).
-   **Métricas**:
    -   `Gasto Real`: Lo que AgentShield pagó a OpenAI/Anthropic.
    -   `Coste Estimado`: Lo que hubiera costado si se usara siempre GPT-4.
    -   `ROI`: (Coste Estimado - Gasto Real).

### B. Auditoría Forense ("Legal View")
**Ruta**: `src/app/(dashboard)/dashboard/receipts/page.tsx`
**Estado**: ✅ Implementado (Fase 4)

#### Estrategia
Proveer prueba matemática de inocencia y cumplimiento ("Digital Notary").

#### Detalles de Implementación
1.  **Backend**: `GET /v1/audit/public-key` expone la clave pública RSA (PEM).
2.  **Frontend**:
    -   Botón "Verify" en cada fila de tabla.
    -   **`VerificationModal`**:
        -   Calcula SHA-256 del contenido del recibo (Client-side o simulación).
        -   Muestra el Hash encadenado (`previous_hash`).
        -   Verifica visualmente la firma RSA con la clave pública.
    -   Indicadores de estado: `Verifying...` -> `Signature Valid` (Verde) / `Corrupted` (Rojo).

### C. Economía de Conocimiento ("Futuristic View")
**Componente**: `src/components/3d/market-scene.tsx`
**Estado**: 🏗️ Concepto

#### Estrategia
Hacer visible el flujo de datos invisible. Usar gráficos 3D (Three.js/React Three Fiber) para mostrar transacciones volando entre nodos (Departamentos).
-   **Visual**: Nodos brillantes que representan Depts (HR, Tech, Sales).
-   **Partículas**: Cada token generado es una partícula que viaja.
-   **Royalties**: Cuando Marketing usa un prompt de Ventas, se visualiza una transferencia de créditos.

### D. Sostenibilidad ("ESG View")
**Ruta**: `src/app/(dashboard)/dashboard/sustainability/page.tsx`
**Estado**: 🟡 Conectado a Backend

#### Estrategia
Convertir la eficiencia computacional en métricas ESG (Environmental, Social, Governance).

#### Detalles de Implementación
-   **Backend**: `GET /v1/analytics/sustainability`
    -   Usa RPC `get_total_carbon` en Supabase para suma atómica rápida.
    -   Constantes: 1 Árbol = 57g CO2 absorción/día.
-   **Frontend**:
    -   Muestra "Árboles Plantados" (Equivalencia).
    -   Rating Energético (A+ para servidores EU, B para US).
    -   Botón "Download Certificate" para cumplimiento de normativa (EU AI Act).

---

## Roadmap de Integración
1.  **Auditoría (Receipts)**: ✅ Completado. Firma RSA verificable en UI.
2.  **Sostenibilidad**: Siguiente paso. Conectar `page.tsx` con endpoint real `v1/analytics/sustainability`.
3.  **Finanzas**: Implementar endpoint de series temporales para `spending-chart`.
4.  **3D Market**: Implementación final (Wow Factor).
