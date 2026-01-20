# 12. AgentShield OS: El Sistema Operativo Empresarial

> **Estado**: ✅ Implementado (Full Stack)
> **Versión**: 1.0
> **Concepto**: AgentShield no es solo un proxy; es un sistema operativo que gestiona Reputación, Finanzas y Conocimiento.

---

## 1. El Motor de Confianza (Trust Engine) ⚖️
Pasamos de un modelo binario (Allow/Block) a uno probabilístico basado en reputación.

### Arquitectura de Puntuación
Cada usuario tiene un `trust_score` (0-100) en su perfil.
*   **Inicio**: 100 puntos.
*   **Penalización (-5)**: Si violas una política crítica (BLOCK).
*   **Recuperación (+1)**: (Planned) Por cada 100 transacciones seguras.

### Niveles de Riesgo
*   🟢 **LOW (80-100)**: Acceso a GPT-4, Herramientas críticas, Aprobación automática.
*   🟡 **MEDIUM (50-79)**: Acceso restringido, requiere aprobación humana para herramientas financieras.
*   🔴 **HIGH (0-49)**: Sandbox total. Solo modelos locales/baratos. Sin acceso a herramientas.

**Implementación**: `app/services/trust_system.py`

---

## 2. Economía del Conocimiento (Internal Royalties) 🏦
Resolvemos el problema del "Free Rider" en la gestión del conocimiento.

### Cómo Funciona
1.  **Contribución**: Juan sube `Manual_Ventas_2025.pdf` al Vault.
2.  **Uso**: María pregunta al Chat "¿Cómo cierro una venta?".
3.  **RAG**: El sistema usa el PDF de Juan para responder.
4.  **Pago**: El sistema calcula el coste de la query (ej: $0.10) y "paga" un royalty (20% = $0.02) a Juan.

### Ledger Interno
La tabla `internal_ledger` actúa como libro contable inmutable para estas micro-transacciones.
*   **Concepto**: `KNOWLEDGE_ROYALTY`
*   **Visualización**: Componente `KnowledgeEarnings` en el Dashboard.

**Implementación**: `app/services/settlement.py`

---

## 3. Servidor MCP (Model Context Protocol) 🤖
AgentShield ahora habla el idioma nativo de las IAs (Claude Desktop, IDEs, Agentes Autónomos).

### Herramientas Expuestas
Tu servidor MCP (`mcp_server.py`) expone estas funciones a cualquier agente conectado:

| Herramienta | Descripción |
| :--- | :--- |
| `get_user_trust_profile(email)` | Consulta el nivel de confianza y riesgo de un empleado. |
| `get_forensic_timeline(trace_id)` | "CSI Mode". Devuelve la reconstrucción forense de un incidente. |
| `list_knowledge_royalties(user_id)` | Consulta financiera de ganancias por conocimiento. |
| `create_dynamic_policy(...)` | Permite al Admin crear reglas de bloqueo via Chat natural. |
| `search_knowledge_vault(query)` | Buscador RAG seguro sobre documentos corporativos. |

```bash
python mcp_server.py
```
Esto levanta un servidor stdio/SSE compatible con cualquier cliente MCP.

---

## 4. Robustez y Anti-Abuso 🛡️
Mecanismos implementados para producción real (2026 Ready).

### Anti-Gaming (Prevención de Fraude)
Evitamos que los usuarios "farmeen" royalties consultando sus propios documentos repetidamente.
*   **Regla Self-Pay**: No puedes cobrar por tus propias consultas.
*   **Rate Limit (Redis)**: Máximo 10 pagos por el mismo documento/día.
*   **Implementación**: `app/services/settlement.py`

### Rendimiento (Zero Latency)
La contabilidad no bloquea la experiencia del usuario.
*   **Background Tasks**: El cálculo de royalties y reputación ocurre *después* de enviar la respuesta al usuario.
*   **Implementación**: `app/routers/proxy.py` (inyección en `post_process`).

### Trust Healer (Redención Automática)
Un sistema justo permite la rehabilitación.
*   **Worker**: `app/workers/trust_healer.py`
*   **Lógica**: Recupera **+1 punto** de confianza cada 24h si no hay incidentes.
*   **RPC**: Función SQL `heal_trust_scores()` en base de datos.

---

## 5. Sovereign Knowledge Marketplace (Mercado Interno) 🏛️
AgentShield permite a los departamentos comercializar su conocimiento.

### Conceptos Clave
*   **Collections**: Paquetes de documentos (ej: "Legal Contracts 2025").
*   **Listings**: Reglas de precio y acceso (ej: "$0.05/query", "Solo Marketing").
*   **Licenses**: 
    *   `FULL_ACCESS`: RAG normal.
    *   `SUMMARY_ONLY`: El LLM solo ve un resumen ofuscado, nunca el original.
    *   `CITATION_ONLY`: Solo se permite citar la existencia del documento.

### Revenue Share
Los beneficios se reparten automáticamente a los creadores definidos en `revenue_splits`.
*   Ejemplo: 50% al creador del documento, 50% al fondo del departamento.

**Implementación**: `app/services/marketplace.py` y `scripts/seed_marketplace.sql`.

### Experiencia de Usuario (Frontend) 🎨
El "Comercio Contextual" se integra directamente en el chat.
*   **Hook**: `useMarketplace` gestiona la compra asíncrona.
*   **Componente**: `PaywallCard.tsx` muestra el contenido ofuscado (blur) y el precio.
*   **Flujo**: 
    1.  El Backend detecta contenido de pago y envía un bloque `paywall_teaser`.
    2.  El Frontend renderiza la `PaywallCard`.
    3.  El usuario compra -> La tarjeta se desbloquea visualmente -> Se revela el contenido real.

---

## 6. Semantic Budgeting (El cerebro del CFO) 🧠
El sistema ya no solo cuenta tokens, entiende **intenciones**.

### Clasificador Dinámico
*   Analiza el prompt del usuario y lo etiqueta (ej: `CODING`, `LEGAL`, `GAMING`) usando definiciones vivas en DB.
*   **Reglas Semánticas**:
    *   **BLOCK**: "Marketing no puede hacer `CODING`".
    *   **PENALTY**: "Legal puede hacer `CREATIVE`, pero le cuesta **2.5x**".

### Implementación
*   `app/services/semantic_router.py`: Motor de clasificación.
*   `seed_semantic_budget.sql`: Esquema de reglas e intenciones.

---

## 7. Forensic Time-Travel (Auditoría Total) ⏳
Probando el pasado con criptografía.

### El Problema
En una auditoría legal en 2028, ¿cómo demuestras que la regla de privacidad estaba activa hoy?

### La Solución: Snapshots
1.  Cada request genera un **Hash SHA256** del estado completo de la configuración (Políticas + Presupuestos + Herramientas).
2.  Este hash se guarda en el "Recibo Forense" de la transacción.
3.  La tabla `config_snapshots` guarda el contenido real de ese hash.
4.  Resultado: Prueba matemática inmutable del "Universo de Reglas" en ese instante exacto.

**Implementación**: `app/services/snapshotter.py`.

---

## 8. White-Label & Domain Resolution (Zero Install) 🏳️
La experiencia final del cliente: `chat.cocacola.com` con sus colores, sin rastro de AgentShield.

### Arquitectura
### Arquitectura de Resolución
Soportamos dos modos de despliegue para el cliente:

1.  **Modo Gestionado (Managed Subdomain) - Zero Effort**: 
    - El Admin crea el tenant con el slug `cocacola`.
    - La URL es inmediatamente `cocacola.agentshield.com`.
    - **El cliente no hace nada.**
2.  **Modo Custom (Custom Domain)**: 
    - El cliente configura un CNAME de `chat.cocacola.com` a `app.agentshield.com`.
    - Se mapea en AgentShield como dominio exclusivo.

**Implementación**: `app/routers/public_config.py` y `scripts/seed_whitelabel.sql`.

---

## 9. Trust Engine & Behavioral Governance ⚖️
AgentShield gestiona la reputación del usuario para un gobierno justo.
- **Normal (70-100)**: Acceso total. Restaura +5 puntos cada 24h de "Clean Sheet".
- **Restricted (30-69)**: Downgrade automático a modelos seguros.
- **Supervised (<30)**: Bloqueo crítico con requerimiento de aprobación manual.

## 10. Green AI & ESG Compliance 🌿
- **Carbon Budgets**: El CFO puede establecer límites de gCO2 por departamento.
- **Eco-Routing**: Desvío a modelos eficientes (`agentshield-eco`) si la tarea es trivial.
- **Sustainability Ledger**: Registro de emisiones y "Carbon Avoided" para reportes ESG.

## 11. DPO-as-Code (Automated Compliance) ⚖️
- **Right to Forget**: Purga quirúrgica de PII manteniendo la integridad financiera del tenant.
- **Instant Certification**: Generación de certificados PDF firmados criptográficamente para auditorías.
- **Audit Ledger**: Cada acción de gobierno queda sellada y vinculada a un certificado inmutable.

## 12. Sistema Inmunológico (Event Bus & SOC) 🚨
AgentShield no solo observa; reacciona en tiempo real a las amenazas.
- **Event Bus**: Log centralizado hich-speed para eventos de seguridad (PII_BLOCKED, TRUST_DROP).
- **Automated Playbooks**: Reglas de reacción inmediata (ej: Si hay PII crítica -> Degradar modelo automáticamente).
- **Multichannel Alerts**: Notificaciones instantáneas a Slack, Teams o Webhooks personalizados para el equipo de SecOps.

## 13. Enterprise Internal Invoicing (Chargeback) 💰
AgentShield transforma la IA de un "coste central" a un modelo de "pago por uso responsable" entre departamentos.
- **Gross vs Net Audit**: Cada transacción registra el coste del modelo original pedido y el ahorro generado por AgentShield.
- **Monthly Chargeback PDF**: Facturas profesionales generadas automáticamente para cada centro de coste.
- **Knowledge Royalties**: Los departamentos que aportan conocimiento (RAG/Docs) pueden recibir créditos que compensan su gasto.

---
**AgentShield OS: El Soberano de la IA Empresarial.**
