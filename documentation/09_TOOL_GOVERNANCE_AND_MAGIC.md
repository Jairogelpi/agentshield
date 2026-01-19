# 09. Gobierno de Herramientas y Capa Mágica (The Magic Layer)

> **Estado**: ✅ Completado
> **Versión**: 1.0

AgentShield ha evolucionado más allá de un simple proxy de texto. Con la introducción del "Tool Governance" y el "Policy Copilot", el sistema ahora es capaz de controlar acciones tangibles (buscar en la web, ejecutar código, generar imágenes) y permite a los administradores definir reglas hablando en lenguaje natural.

## 1. El Motor de Gobierno (`tool_governor.py`)

El corazón del control sobre las capacidades de la IA.

### Cómo Funciona
A diferencia de los proxies tradicionales que solo filtran texto, AgentShield intercepta el bloque `tool_calls` del payload del LLM antes de que llegue al cliente.

1.  **Intercepción**: Cuando el LLM decide usar una herramienta (ej: `stripe_charge`), el proxy pausa la respuesta.
2.  **Evaluación**: El `ToolGovernor` consulta la tabla `tool_policies` cruzando:
    *   **Herramienta**: ¿Qué quiere ejecutar?
    *   **Identidad**: ¿Quién es el usuario? (Rol, Departamento)
    *   **Argumentos**: ¿Qué parámetros envía? (ej: `amount > 500`)
3.  **Decisión**:
    *   `ALLOW`: La herramienta pasa tal cual.
    *   `BLOCK`: Se reemplaza la llamada con una notificación de sistema ("Acción bloqueada por política").
    *   `REQUIRE_APPROVAL`: Se crea una entrada en `tool_approvals` (estado PENDING) y se notifica al usuario que necesita autorización humana.

### Esquema de Datos (`tool_policies`)
Las reglas se definen en JSON estricto:
```json
{
  "tool_id": "uuid-stripe",
  "target_dept_id": "uuid-marketing",
  "action": "BLOCK",
  "argument_rules": {
    "amount": { "gt": 500 }
  }
}
```

---

## 2. La Capa Mágica: Policy Copilot (`policy_copilot.py`)

Interfaz de lenguaje natural para configurar la seguridad. "Texto a Política".

### Arquitectura Neuronal
En lugar de formularios complejos, usamos un LLM (el "Compilador de Políticas") que:
1.  **Lee el Contexto**: Carga las definiciones de herramientas (`tool_definitions`) y departamentos reales de la DB.
2.  **Interpreta la Intención**: Traduce "Nadie de Finanzas puede borrar bases de datos" a una regla JSON.
3.  **Genera Borrador**: Devuelve un objeto JSON listo para ser insertado en `tool_policies`.

### Flujo de Usuario
1.  Admin escribe: *"Bloquear generación de imágenes HD para Becarios"*.
2.  Backend genera:
    ```json
    {
      "tool_name": "image_generation",
      "target_role": "intern",
      "argument_rules": { "quality": "hd" },
      "action": "BLOCK"
    }
    ```
3.  Frontend muestra una tarjeta de previsualización ("Draft").
4.  Admin confirma y la regla se activa en tiempo real.

---

## 3. Paridad Multimodal y Facturación

AgentShield ahora soporta y cobra correctamente por capacidades "Human-Like".

### A. Visión (`estimator.py`)
El sistema ya no es ciego.
-   **Detección**: El proxy analiza los mensajes buscando `type: image_url`.
-   **Coste**: Se aplica un cargo dinámico (aprox. $0.0038/img) basado en el precio actual en `model_prices`.
-   **Lógica**: `total_cost = (tokens_in * price) + (tokens_out * price) + (img_count * vision_price)`.

### B. Creatividad (DALL-E 3)
Nuevo router dedicado `/v1/images/generations`.
-   **Interceptación**: Captura peticiones al endpoint de imágenes compatible con OpenAI.
-   **Presupuesto**: Verifica fondos antes de la generación (coste alto: $0.04 - $0.08).
-   **Auditoría**: Registra la metadata de la imagen (prompt, size, quality) en el recibo forense.

### C. Herramientas Registradas (`tool_definitions`)
Para que el Gobernador funcione, las capacidades son tratadas como herramientas estandarizadas en SQL:
-   `web_search`: Búsqueda en internet ($0.01/exec).
-   `python_interpreter`: Ejecución de código ($0.05/exec).
-   `image_generation`: Creación de activos visuales ($0.04/exec).

---

## Resumen de Tablas Clave
-   `tool_definitions`: Catálogo de lo que la IA puede hacer.
-   `tool_policies`: Reglas de quién puede hacer qué.
-   `tool_approvals`: Cola de trabajo para acciones sensibles ("Human-in-the-Loop").
-   `model_prices`: Lista de precios vivos para tokens y assets multimedia.
