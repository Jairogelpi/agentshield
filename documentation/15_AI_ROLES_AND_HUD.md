# 15. AI Role Architect & HUD Cockpit

## 1. Visión General
AgentShield ha evolucionado de un proxy de seguridad a una **Plataforma de Inteligencia Operativa**. Esta actualización introduce dos pilares fundamentales:
1.  **AI Role Architect**: Generación automática de identidad operativa y reglas de seguridad mediante IA.
2.  **Live HUD Protocol (LHP)**: Protocolo de streaming que inyecta telemetría financiera y ecológica en tiempo real, visualizada en un Cockpit dedicado.

---

## 2. AI Role Architect ("Magic Create")

### 2.1 Concepto
En lugar de configurar manualmente permisos RBAC y prompts de sistema complejos, el administrador simplemente describe el puesto de trabajo en lenguaje natural. AgentShield utiliza un "Meta-Agente" para diseñar la configuración óptima.

### 2.2 Flujo Técnico
1.  **Input**: "Necesito un auditor junior que revise facturas pero no vea salarios."
2.  **RoleGenerator (`app/services/role_generator.py`)**:
    *   Usa `gpt-4o` (vía Gateway) para traducir la intención.
    *   Genera un JSON con:
        *   `system_persona`: Prompt optimizado ("You are a strict financial auditor...").
        *   `pii_policy`: Regla de DLP (ej. `REDACT` para emails, `BLOCK` para SSN).
        *   `allowed_modes`: Selección de modelos permitidos (ej. `["agentshield-secure"]`).
3.  **Persistencia**: Se guarda en la tabla `role_definitions`.
4.  **RoleFabric (`app/services/roles.py`)**:
    *   Servicio de lectura de alta velocidad con caché en memoria.
    *   Evita latencia en cada llamada al chat recuperando el rol por `(Tenant, Dept, Function)`.

### 2.3 Componentes
*   **Backend**: `app/routers/admin_roles.py` (Endpoint `/ai-provision`).
*   **Frontend**: `src/components/admin/ai-role-generator.tsx`.

### 2.4 Metadatos de Seguridad (V2)
El "Role Architect" no solo genera un prompt, sino reglas técnicas (`metadata.active_rules`):
*   `active_rules`: Lista de guardrails visibles para el usuario (ej. `["No Crypto Advice", "DLP Strict"]`).
*   Estas reglas viajan desde la DB hasta el **Proxy** y luego al **Frontend** para mostrarse en el panel lateral.

---

## 3. Live HUD Protocol (LHP) & Visual Guardrails

### 3.1 El Problema
En los sistemas tradicionales, el usuario final es "ciego" al coste, impacto ambiental y riesgo de sus consultas.

### 3.2 La Solución AgentShield
Inyectamos la telemetría **dentro** del stream de respuesta del LLM.

### 3.3 Visual Guardrails (Cockpit)
En la V2, el panel lateral (`HudCockpit`) recibe dinámicamente las reglas activas.
*   Si el rol es "Legal", el usuario ve un badge `🛡️ Attorney-Client Privilege`.
*   Esto refuerza la "Identidad Operativa" en tiempo real.

### 3.4 Arquitectura de Streaming (`app/routers/proxy.py`)
El endpoint `universal_proxy` utiliza `stream_with_hud_protocol`:
1.  **Relay**: Pasa los chunks del LLM (OpenAI/Anthropic) tal cual llegan.
2.  **Injection (Final del Stream)**:
    *   **Canal Visual (Markdown)**: Inyecta una tarjeta compatible con cualquier cliente de chat.
    *   **Canal de Datos (SSE)**: Inyecta `active_rules`, `trust_score` y métricas financieras.

### 3.4 HUD Cockpit (`src/components/chat/hud-cockpit.tsx`)
El frontend de AgentShield captura el evento `agentshield.hud` y actualiza un panel lateral (Side Panel) en tiempo real.
*   **Store Global**: `useHudStore` (Zustand) mantiene el estado de la última métrica.
*   **Experiencia**: El usuario ve cómo sus acciones impactan en el presupuesto y la huella de carbono al instante.

---

## 4. Estructura de Datos (`app/services/hud.py`)

La clase `HudMetrics` estandariza el intercambio de datos:
*   `trust_score`: Nivel de confianza (0-100) basado en reglas de `trust_system`.
*   `savings_usd`: Dinero ahorrado por Arbitraje + Caché.
*   `co2_saved_grams`: Emisiones evitadas por usar modelos eficientes o data centers verdes.
*   `role`: La "máscara" operativa activa en esa sesión.

## 5. Implementación Frontend
*   **Chat Page**: `src/app/(dashboard)/chat/page.tsx`.
*   **Cockpit Widget**: `src/components/chat/hud-cockpit.tsx`.
*   **Admin UI**: `src/app/(dashboard)/admin/roles/page.tsx`.
