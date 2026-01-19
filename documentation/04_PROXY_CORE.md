# 🧠 Módulo 4: El Núcleo de Inteligencia (`The Core`)

> **Foco**: Enrutamiento, Caché Semántico y Resiliencia.
> **Archivos Clave**: `app/routers/proxy.py`, `app/services/cache.py`, `app/limiter.py`.

---

## 1. El Router Universal (`app/routers/proxy.py`)
Este archivo es el corazón del sistema (500+ líneas). Orquesta la sinfonía entre Seguridad, Finanzas e IA.

### Flujo de Vida de una Petición
1.  **Autenticación**: Verifica quién eres (`verify_api_key`).
2.  **Configuración Dinámica**: Carga tu presupuesto y reglas desde `get_function_config`.
3.  **PII Guard**: Limpia tus datos *antes* de seguir.
4.  **Caché Semántico**: ¿Ya preguntaste esto antes? (Si sí -> Respuesta instantánea).
5.  **Arbitraje**: ¿Debemos cambiar de modelo para ahorrar?
6.  **Ejecución**: Llama a OpenAI/Anthropic/Local.
7.  **Auto-Corrección**: Si la respuesta es mala, penaliza al modelo (RL).

---

## 2. Caché Semántico ("The Helicone Killer")
La mayoría de proxies usan un hash simple de la petición. Si cambias una coma, el caché falla. AgentShield usa **VECTORES**.

### Tecnología (`app/services/cache.py`)
1.  **Embeddings**: Convierte el prompt en un vector de 384 dimensiones usando `FlashRank` o `All-MiniLM` (Local).
2.  **Búsqueda de Similitud**: Usa Redis Vector Search.
3.  **Umbral de Similitud (0.92)**:
    *   *Prompt A*: "¿Cuánto cuesta el plan Pro?"
    *   *Prompt B*: "Precio del plan profesional"
    *   *Resultado*: **CACHE HIT**. El sistema entiende que significan lo mismo.
    *   **Ahorro**: $0.00 y 5ms de latencia.

---

## 3. Rate Limiting (`app/limiter.py`)
Protegemos tu infraestructura y tu cartera.
*   **Token Bucket**: Implementación estándar para evitar ataques DDoS.
*   **Límites por Coste**: No solo limitamos "10 peticiones/seg", sino "$5 dólares/minuto". Esto es crítico cuando usas modelos caros como GPT-4, donde 1 sola petición puede costar $1.

---

## 4. Resiliencia y Fallbacks
El Proxy nunca se rinde.
*   **Provider Swapping**: Si OpenAI devuelve `503 Service Unavailable`, el sistema captura la excepción y reintenta automáticamente con Azure OpenAI o Anthropic (si está configurado como fallback).
*   **Interruptor de Apagado**: Si el presupuesto se agota, el proxy corta el grifo instantáneamente (HTTP 402), evitando sorpresas en la factura a fin de mes.

---

## 5. Resumen de Decisiones (Pros/Contras)

| Decisión | Por qué es brillante (Pros) | Riesgo (Contras) |
| :--- | :--- | :--- |
| **Caché Semántico** | Ahorra dinero incluso cuando los usuarios no repiten las frases exactas. | Riesgo de "Falso Positivo" (devolver una respuesta vieja a una pregunta sutilmente distinta). Mitigado con umbral alto (0.92). |
| **Model Swapping** | Garantiza 99.99% de Uptime aunque caiga un proveedor. | Puede causar inconsistencias si un modelo formatea la respuesta distinto al original. |
| **Lógica en Proxy** | Centraliza el control. No hay que tocar el código de las apps cliente. | Añade latencia (~150ms) a cada petición. |
