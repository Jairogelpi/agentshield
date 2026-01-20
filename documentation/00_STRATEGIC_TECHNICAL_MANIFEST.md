# 🛡️ AgentShield OS: El Manifiesto Técnico Estratégico
> **De la Gobernanza Pasiva a la Ejecución Soberana de IA**

Este documento consolida la arquitectura implementada en el código, demostrando a inversores y CTOs por qué AgentShield es el nuevo estándar.

---

## 1. Tesis de Producto: "El Guardián en la Puerta"
Mientras que los líderes actuales (OneTrust, Credo AI) se centran en el Compliance Descriptivo, AgentShield OS introduce el **Compliance Ejecutivo**. No preguntamos si un documento es sensible; lo leemos en memoria y aplicamos la ley en el milisegundo en que ocurre la transacción.

---

## 2. Los Cuatro Pilares del Dominio Técnico

### I. Seguridad Activa Multimodal (The Sentinel)
Hemos resuelto la exfiltración de datos en todos los formatos.

*   **Inspección en RAM (<5ms)**:
    *   **Implementación**: `app/services/pii_guard.py` & Rust Core.
    *   **Mecanismo**: Intercepción nativa sin persistencia en disco.
*   **IA Semántica Local**:
    *   **Implementación**: `app/services/semantic_guardian.py`.
    *   **Mecanismo**: Clasificación NLI (Natural Language Inference) que distingue contexto real vs educativo.
*   **Visión Artificial (OCR)**:
    *   **Implementación**: `app/services/ocr_service.py` (Tesseract).
    *   **Mecanismo**: Bloqueo del "hueco analógico" (pantallazos, IDs escaneados) antes de llegar al LLM.

### II. Arbitraje Financiero y Green AI (The CFO)
Transformamos la seguridad de centro de costes a centro de beneficios.

*   **Real-Time Arbitrage**:
    *   **Implementación**: `app/services/arbitrage.py`.
    *   **Mecanismo**: Selección dinámica de modelos (GPT-4 vs Haiku) basada en complejidad computacional.
*   **Ledger de Carbono**:
    *   **Implementación**: `app/services/carbon.py`.
    *   **Mecanismo**: Certificación de "CO2 evitado" por query, integración ESG nativa.

### III. Role Fabric: Identidad Operativa Universal (The Architect)
Eliminamos la fricción de configuración mediante AI-Driven Provisioning.

*   **Provisión Natural**:
    *   **Implementación**: `app/services/role_architect.py` & `/admin/roles`.
    *   **Mecanismo**: GPT-4o traduce "Ventas LATAM" a JSON técnico técnico (System Prompts + Reglas).
*   **Zero-Touch Enforcement**:
    *   **Implementación**: `app/services/roles.py` & `proxy.py`.
    *   **Mecanismo**: Inyección invisible de la "Identidad Operativa" y presentación visual en el **HUD Cockpit**.

### IV. Gobernanza Forense y Probatoria (The Auditor)
Evidencia legal matemática en lugar de promesas.

*   **Evidence-Based Reporting**:
    *   **Implementación**: `app/services/compliance.py` & `legal_rag.py`.
    *   **Mecanismo**: Informes PDF que citan artículos legales reales (GDPR/EU AI Act) vinculados a logs inmutables.
*   **Forensic Time-Travel**:
    *   **Implementación**: `app/services/snapshotter.py`.
    *   **Mecanismo**: Hash criptográfico de la configuración en el momento exacto del incidente.

---

## 3. Estrategia de Despliegue: Libertad vs. Control
Arquitectura BYOC (Bring Your Own Cloud) que elimina el dilema de infraestructura.

*   **Nivel SaaS**: Onboarding instantáneo (`seed_whitelabel.sql`).
*   **Nivel Sovereign**: Despliegue en contenedores Docker aislados (`docker-compose.yml`) para Defensa/Banca.

---

## 4. El "Moat" (Foso Defensivo)
*   **Fricción Negativa**: Aprendizaje por refuerzo vía HITL (`quarantine_service.py`).
*   **Integración Profunda**: Capa de transporte (Proxy), no plugin.
*   **Privacidad por Diseño**: Ejecución local en CPU (Rust/ONNX).

---

> "OneTrust os dice que estáis en peligro. Lakera os pone una valla. **AgentShield OS os da el control absoluto sobre el cerebro de vuestra empresa.**"
