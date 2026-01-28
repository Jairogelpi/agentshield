# 🗺️ Mapa de Rutas de AgentShield (Routers Overview)

El directorio `app/routers/` es el sistema nervioso de AgentShield. Aquí es donde se definen todos los puntos de entrada (endpoints) que el mundo exterior puede usar para interactuar con nuestro sistema.

Hemos organizado los **20 módulos** en 5 categorías lógicas para entender mejor el producto final:

---

## 1. 🚀 El Motor Central (Gateway & Core)
Estos son los archivos más críticos, por donde pasa el tráfico de IA en tiempo real.
*   **`proxy.py`**: El túnel principal. Recibe el prompt del usuario y devuelve la respuesta de la IA ya filtrada y protegida.
*   **`authorize.py`**: El cerebro financiero. Decide si una petición se permite basándose en presupuesto y políticas.
*   **`receipt.py`**: El notario digital. Firma y registra cada céntimo gastado y cada token usado.

## 2. 🛡️ Cumplimiento y Seguridad (Compliance)
Aseguran que el uso de la IA sea legal, auditable y seguro.
*   **`compliance.py`**: Genera certificados de auditoría y reportes de cumplimiento (ej. EU AI Act).
*   **`audit.py`**: El historial inmutable de todas las acciones importantes.
*   **`forensics.py`**: Herramientas para investigar incidentes de seguridad o fugas de datos.
*   **`webhooks.py`**: Avisa a sistemas externos (Slack, Email) cuando algo importante ocurre.

## 3. 📊 Negocio y Experiencia (Dashboard & Business)
Lo que el cliente ve en su panel de control.
*   **`dashboard.py`**: Gestiona las políticas, los límites de gasto y la configuración del tenant.
*   **`analytics.py`**: Gráficos y datos sobre cuánto dinero se está ahorrando y cómo se usa la IA.
*   **`invoices.py`**: Gestión de facturación y suscripciones.
*   **`feedback.py`**: Recoge si la IA lo está haciendo bien o mal según los usuarios.

## 4. 🧠 Inteligencia y Capacidades (AI Tools)
Funciones avanzadas que potencian a la IA.
*   **`embeddings.py`**: Gestión de memoria vectorial y búsqueda semántica.
*   **`tools.py`**: Conexiones de la IA con el mundo real (navegar por internet, ejecutar código).
*   **`trust.py`**: Evalúa qué tan "confiable" es una respuesta de la IA.
*   **`images.py`**: Control y filtrado de generación de imágenes.

## 5. ⚙️ Administración y Onboarding (Ops)
Gestión interna y alta de nuevos clientes.
*   **`onboarding.py`**: El proceso de bienvenida y configuración inicial de una empresa.
*   **`admin_roles.py`**: Creación inteligente de roles (ej. "Solo programadores") usando IA.
*   **`admin_chat.py`**: El chat directo con el "Arquitecto" del sistema.
*   **`public_config.py`**: Datos que el frontend necesita saber antes de que el usuario haga login.

---

### ¿Cómo afecta esto al programa?
Cada archivo es una **responsabilidad separada**. Si queremos cambiar cómo se facturan los tokens, sabemos que tenemos que ir a `receipt.py` o `invoices.py` sin riesgo de romper el `proxy.py`. Esta modularidad es lo que hace que AgentShield sea estable y fácil de escalar.
