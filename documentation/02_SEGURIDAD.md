# 🛡️ Módulo 2: El Escudo de Seguridad (`The Shield`)

> **Foco**: Privacidad, Compliance (GDPR/SOC2) y Autenticación Zero-Trust.
> **Archivos Clave**: `app/services/pii_guard.py`, `app/logic.py`, `app/main.py`.

---

## 1. Filosofía de Seguridad: "Paranoia Constructiva"
AgentShield asume un escenario hostil por defecto:
1.  **Zero Trust**: No confiamos en la red interna. Cloudflare es el primer portero.
2.  **Stateless**: No guardamos sesiones en RAM que puedan ser robadas. Todo token se valida criptográficamente en cada petición.
3.  **Data Sovereignty**: Tu PII (Información Personal Identificable) nunca sale de tu servidor. Literalmente.

---

## 2. Autenticación Multifactor de Máquinas (Hybrid Auth)
En `app/logic.py`, implementamos un sistema dual que rara vez se ve en proyectos simples:

### A. Para Humanos (Frontends/Dashboards) -> JWT
*   **Mecanismo**: Token firmado con `HS256`.
*   **Ventaja**: El servidor no consulta la base de datos para validar cada click. Ahorra IOPS y milisegundos.
*   **Seguridad**: Expiración corta (10 mins) para minimizar riesgo de robo.

### B. Para Robots (Scripts/Backend) -> API Keys Opacas
*   **Mecanismo**: `sk_live_837...`.
*   **Zero-Downtime Rotation**:
    *   Soportamos una "Llave Secundaria" en base de datos.
    *   Si rotas la llave principal, tus scripts viejos siguen funcionando 24h usando la secundaria. Esto evita que tu producción se caiga durante una rotación de seguridad.
*   **Hashing**: guardamos `SHA256(key)`, nunca la llave real. Si nos roban la base de datos, los hackers solo obtienen basura inútil.

---

## 3. PII Guard: El Firewall de Datos (`app/services/pii_guard.py`)
Este es el componente más crítico para clientes de Banca y Salud.

### El Problema
Enviar "Hola, mi tarjeta es 4444..." a OpenAI es una violación de GDPR instantánea.

### La Solución: Capas de Defensa
Implementamos una defensa en profundidad que se ejecuta *antes* de salir a Internet.

| Capa | Tecnología | Latencia | Qué detecta |
| :--- | :--- | :--- | :--- |
| **1. Estructural** | **Rust Regex** | < 1ms | Emails, Tarjetas de Crédito, DNI, SSN. |
| **2. Semántica** | **Small Language Model (ONNX)** | ~20ms | "Me llamo **Juan**" (Nombres, Direcciones, Contexto). |
| **3. Cloud** | **LLM Dedicado** (Opcional) | ~500ms | Casos muy complejos (Solo si activa 'Paranoid Mode'). |

### ¿Por qué ONNX Local? (Decisión Clave)
Muchos competidores usan una API externa para limpiar datos (ej. AWS Comprehend).
*   **El Riesgo**: Para limpiar los datos, primero tienes que enviárselos a AWS. Ya han salido de tu perímetro.
*   **Nuestra Ventaja**: Corremos un modelo BERT cuantizado (`FlashRank`/`Tokenizers`) en la propia CPU del contenedor Docker. Los datos se limpian en la memoria RAM del servidor. **Privacidad Matemática**.

---

## 4. Middleware de Cloudflare (`app/main.py`)
En las líneas 170-200 de `main.py`:
*   Validamos la cabecera `X-AgentShield-Auth`.
*   Esta cabecera es inyectada por Cloudflare Edge.
*   Si alguien intenta atacar tu IP directamente (bypass del WAF), el servidor rechaza la conexión instantáneamente. Es un túnel virtual privado sobre Internet público.

---

## 5. Resumen de Decisiones (Pros/Contras)

| Decisión | Por qué es brillante (Pros) | Riesgo (Contras) |
| :--- | :--- | :--- |
| **Hybrid Auth** | Sirve a humanos y robots con una sola API. | Código de validación más complejo (`verify_api_key` tiene 60 líneas). |
| **PII Local (CPU)** | Cero fugas de datos. Cumplimiento legal total. | Consume ~300MB RAM. Reduce la concurrencia máxima por servidor. |
| **Hashing de Keys** | Si nos hackean la DB, estamos seguros. | No podemos mostrarle al usuario su llave "perdida", tiene que regenerarla. |

---

## 6. FileGuardian: Protección de Archivos (`app/services/file_guardian.py`)
AgentShield extiende su seguridad a los archivos RAG (Uploads), no solo al chat.

### El Problema
Un empleado de Marketing sube "Nóminas_2025.pdf" para resumirlas con IA.
*   **Riesgo 1**: Fuga de datos salariales al modelo de IA.
*   **Riesgo 2**: Ingesta de datos sensibles en el Knowledge Base corporativo (RAG Poisoning).

### La Solución: Gatekeeper Nativo
Interceptamos el flujo en `POST /v1/files` antes de indexar nada.

1.  **Detección de Intención**: Analizamos el archivo (Nombre, tipo, contenido inicial).
2.  **Motor de Políticas Unified**: Reutilizamos la tabla `policies` con `action='BLOCK_UPLOAD'`.
    *   Ejemplo: `{"block_categories": ["INVOICE", "PAYSLIP"]}`
3.  **Auditoría**: Cada bloqueo se registra en `policy_events` junto con los bloqueos de prompts, unificando la visión de seguridad.

**Resultado**: "Marketing" nunca podrá subir archivos financieros, aunque la UI lo permita. El bloqueo es a nivel de API/Infraestructura.
