# 🛡️ AgentShield: Documentación Técnica y Empresarial (Deep Dive)

> **Versión**: 1.0.0 (Enterprise Core)
> **Stack**: FastAPI (Python), Rust (Core Performance), Redis (Cache), Supabase (PostgreSQL), LiteLLM (Gateway).

Este documento es una **radiografía completa** del sistema de AgentShield. No solo explica *qué* hace el código, sino *por qué* se diseñó así, analizando las decisiones técnicas, sus ventajas (Pros) y sus compromisos (Contras).

---

## 📚 Índice de Documentación Modular (Deep Dives)

Hemos desglosado el sistema en guías técnicas ultra-detalladas para cada componente:

### **1.0 Infraestructura**
*   [**01. GENERAL: Arquitectura y Constraints**](documentation/01_INFRAESTRUCTURA.md) - Visión global del diseño híbrido.
*   [01.1 Docker & Deployment](documentation/01.1_INFRA_DOCKER.md) - Análisis del Dockerfile Multi-Stage.
*   [01.2 Rust Core](documentation/01.2_INFRA_RUST.md) - Módulo nativo de alto rendimiento.
*   [01.3 Dependencias](documentation/01.3_INFRA_DEPENDENCIAS.md) - Justificación de `requirements.txt`.

### **2.0 Seguridad (Zero Trust)**
*   [02.1 Lógica de Autenticación](documentation/02.1_AUTH_LOGIC.md) - JWT vs API Keys.
*   [02.2 PII Guard (Privacidad)](documentation/02.2_PII_GUARD.md) - Pipeline Rust -> ONNX -> Cloud.
*   [02.3 Autorización](documentation/02.3_AUTHORIZATION.md) - Reglas de decisión y presupuesto.

### **3.0 Motor Financiero**
*   [03.1 Arbitraje RL](documentation/03.1_ARBITRAGE_RL.md) - Algoritmo Q-Learning (Bandit).
*   [03.2 Sincronización de Precios](documentation/03.2_PRICING_SYNC.md) - Protocolo Espejo.
*   [03.3 Estimador Multimodal](documentation/03.3_ESTIMATOR.md) - Cálculo de costes predictivo.

### **4.0 Proxy & Intelligence**
*   [04.1 Router Universal](documentation/04.1_PROXY_ROUTER.md) - Orquestación de peticiones.
*   [04.2 Semantic Cache](documentation/04.2_SEMANTIC_CACHE.md) - Vectores vs Hash.
*   [04.3 Rate Limiter](documentation/04.3_RATE_LIMITER.md) - Protección DDoS por Tenant.

### **5.0 Observabilidad & Dashboard**
*   [05.1 Green Metrics](documentation/05.1_GREEN_METRICS.md) - Cálculo de CO2.
*   [05.2 Finanzas](documentation/05.2_DASHBOARD_FINANCIALS.md) - Reportes de facturación.
*   [05.3 Políticas](documentation/05.3_DASHBOARD_POLICIES.md) - Configuración y Kill Switch.
*   [05.4 Reportes Streaming](documentation/05.4_DASHBOARD_REPORTS.md) - Exportación masiva CSV.
*   [05.5 Mercado](documentation/05.5_DASHBOARD_MARKET.md) - Matriz de salud y FOMO.
*   [05.6 Sovereign Stats](documentation/05.6_DASHBOARD_SOVEREIGN.md) - Monetización de conocimiento.

---

    
## 1. Arquitectura General: "Stateless & Zero-Trust"

El sistema está diseñado para ser un **Proxy Intermedio** que se sitúa entre el cliente (tu software SaaS) y los proveedores de IA (OpenAI, Anthropic, etc.).

### 📂 Estructura Crítica
*   `app/main.py`: El punto de entrada y orquestador del ciclo de vida.
*   `app/logic.py`: Lógica de negocio pura (Autenticación, Políticas).
*   `app/routers/proxy.py`: El cerebro central que recibe y enruta las peticiones.
*   `app/services/`: Módulos especializados (PII, Arbitraje, Precios).

---

## 2. El Escudo de Seguridad (`app/main.py` y `app/logic.py`)

### 🧠 ¿Qué hace el código?
1.  **Middleware de Cloudflare (`security_guard` en `main.py`)**:
    *   Intercepta *cada* petición HTTP antes de que toque la lógica.
    *   Verifica la cabecera `X-AgentShield-Auth`. Esta es una "llave maestra" que solo Cloudflare posee.
    *   **Efecto**: Si un atacante descubre la IP real de tu servidor y la ataca directamente (saltándose el WAF de Cloudflare), el código lo rechaza inmediatamente.
2.  **Autenticación Híbrida (`verify_api_key` en `logic.py`)**:
    *   Maneja dos tipos de credenciales simultáneamente: **JWTs firmados** (para el Frontend, con caducidad corta) y **API Keys opacas** (`sk_live_...` para scripts backend).
    *   Usa un **Hash SHA256** para buscar la API Key en Redis (Caché) o Supabase (DB). Nunca guarda la llave en texto plano.

### ⚖️ Análisis de Decisiones (Pros y Contras)

#### A. Decisión: Autenticación Híbrida (JWT + Opaque Keys)
*   **✅ PRO (Lo bueno)**:
    *   **Flexibilidad Total**: Permite soportar usuarios humanos en un Dashboard (JWT) y servidores automatizados (API Keys) con el mismo endpoint.
    *   **Seguridad**: Los JWTs evita consultas a base de datos en cada petición (stateless), reduciendo latencia.
*   **❌ CONTRA (Lo malo)**:
    *   **Complejidad**: Mantener dos lógicas de validación aumenta la superficie de errores.
    *   **Revocación JWT**: Es difícil "banear" un JWT teóricamente válido antes de que expire (problema clásico de listas negras distribuidas).

#### B. Decisión: Middleware Zero-Trust (`X-AgentShield-Auth`)
*   **✅ PRO**: Cierra la puerta trasera. Es una práctica de seguridad de nivel bancario. Incluso si hackean tu servidor DNS, no pueden tocar tu API sin pasar por Cloudflare.
*   **❌ CONTRA**: Dificulta el desarrollo local (tienes que comentar el check o simular la cabecera en Postman), aunque hemos puesto un bypass para `ENVIRONMENT=development`.

---

## 3. El Guardián de Privacidad PII (`app/services/pii_guard.py`)

### 🧠 ¿Qué hace el código?
Es un firewall de datos que limpia información sensible *antes* de enviarla a la IA.
1.  **Capa 1 (Rust/Regex)**: Ejecuta expresiones regulares compiladas en Rust (vía librería `rust_module` si disponible, o regex optimizado) para capturar emails, tarjetas de crédito y teléfonos.
2.  **Capa 2 (Sovereign AI)**: Si el regex no es suficiente, ejecuta un modelo **ONNX (BERT Tiny)** localmente en la CPU. Este modelo "entiende" el contexto para detectar nombres propios ("Juan Pérez") que un regex no vería.
3.  **Capa 3 (Cloud Fallback)**: Opcionalmente, llama a una LLM externa para limpieza profunda (raro y lento).

### ⚖️ Análisis de Decisiones

#### A. Decisión: Motor Local (Rust + ONNX) vs API Externa
*   **✅ PRO (La mejor decisión del proyecto)**:
    *   **Privacidad Real**: Los datos se limpian *en tu máquina*. Si usaras una API externa de limpieza (ej. AWS Comprehend), ya habrías enviado los datos fuera, rompiendo el propósito de "Zero Trust".
    *   **Latencia**: Ejecutar ONNX local tarda ~10-50ms. Llamar a una API externa tarda ~500ms. En un proxy, 500ms extra es inaceptable.
*   **❌ CONTRA**:
    *   **Consumo de RAM**: Cargar modelos de IA en memoria (aunque sean pequeños) consume ~300MB de RAM basal, lo que encarece el hosting mínimo (no cabe en una micro-instancia de 128MB).

---

## 4. El Motor Financiero: Arbitraje y Precios (`app/services/arbitrage.py` / `pricing_sync.py`)

### 🧠 ¿Qué hace el código?
Transforma el gasto en IA de un "coste fijo" a un "mercado dinámico".
1.  **Protocolo Espejo (`sync_universal_prices`)**: Al arrancar, el sistema descarga la lista de precios oficial de LiteLLM y OpenRouter y la guarda en Redis. Se convierte en la "Fuente de la Verdad" para calcular márgenes.
2.  **Bandido Contextual (`AgentShieldRLArbitrator`)**:
    *   Analiza cada prompt entrante y le asigna una "Complejidad" (0-100).
    *   Consulta una tabla `Q-Table` en Redis para decidir: *"Para una tarea de complejidad 30, ¿es mejor usar GPT-3.5 o Claude Haiku?"*.
    *   Usa **Reinforcement Learning** (RL): Si elige un modelo barato y este funciona bien (el usuario no reintenta), le da una recompensa positiva. Si falla, negativa.

### ⚖️ Análisis de Decisiones

#### A. Decisión: Reinforcement Learning (RL) en lugar de Reglas "If/Else"
*   **✅ PRO**:
    *   **Adaptabilidad**: El sistema aprende solo. Si sale un modelo nuevo ("Llama-4"), el sistema empezará a probarlo (Exploración) y si es bueno y barato, migrará el tráfico automáticamente sin que tú edites código.
    *   **Invisible Savings**: Logra ahorros marginales masivos al degradar tareas triviales (ej. "Hola", "Gracias") a modelos casi gratuitos sin afectar la calidad percibida.
*   **❌ CONTRA**:
    *   **Problema de "Arranque en Frío"**: Al principio, el sistema no sabe nada y tiene que explorar (probar modelos al azar), lo que puede causar respuestas de baja calidad hasta que converge.
    *   **Complejidad de Depuración**: Si un usuario se queja de una mala respuesta, es difícil saber *por qué* el RL eligió ese modelo específico en ese momento exacto, ya que es probabilístico.

---

## 5. El Núcleo de Inteligencia: Proxy Router (`app/routers/proxy.py`)

### 🧠 ¿Qué hace el código?
Es el controlador principal que orquesta todo.
1.  **Rate Limiting + Presupuestos**: Antes de procesar, verifica en `db.py` y `limiter.py` si el usuario tiene saldo.
2.  **Caché Semántico ("The Helicone Killer")**: Convierte la pregunta del usuario en vectores (números) y busca en Redis si alguien preguntó algo *similar* (distancia coseno > 0.92). Si sí, devuelve la respuesta guardada (gratis e instantánea).
3.  **Self-Correction (Post-Proceso)**: Después de responder, lanza hilos en segundo plano para auditar la calidad y el precio, retroalimentando al motor de RL.

### ⚖️ Análisis de Decisiones

#### A. Decisión: Caché Semántico Vectorial vs Caché Exacto (Hash)
*   **✅ PRO**:
    *   **Inteligencia**: Entiende que "¿Cómo estás?" y "¿Qué tal?" son lo mismo. Un caché normal (Hash) los trataría como distintos, perdiendo oportunidades de ahorro.
*   **❌ CONTRA**:
    *   **Falsos Positivos**: Existe un riesgo (pequeño) de que devuelva una respuesta cacheada para una pregunta que *parece* igual pero tiene un matiz distinto (ej. "¿Quién es el presidente de EEUU en 2020?" vs "... en 2024?"). Hemos mitigado esto subiendo el umbral a 0.92 (muy estricto).

#### B. Decisión: Uso de `LiteLLM` como Librería Base
*   **✅ PRO**: Nos ahorra escribir 100 integraciones. LiteLLM ya sabe cómo hablar con Azure, Bedrock, Vertex, OpenAI, etc. Nos permite centrarnos en la lógica *sobre* la conexión (Arbitraje, Seguridad).
*   **❌ CONTRA**: Dependencia externa fuerte. Si LiteLLM introduce un bug o cambia su API interna, AgentShield se rompe. (Mitigado "congelando" la versión en `requirements.txt`).

---

## 6. Resumen de Valor para el Negocio (Business Case)

### 💎 Fortalezas (Por qué vas a ganar dinero)
1.  **Diferenciación Real**: No eres "otro wrapper de GPT". Eres un **Gateway de Seguridad y Financiero**. Vendes "Compliance en una caja" y "Ahorro Automático".
2.  **Stickiness (Retención)**: Una vez que una empresa conecta sus apps a tu Proxy y ve el Dashboard de ahorros y auditoría, es muy difícil que se vayan (Vendor Lock-in positivo para ti).
3.  **Sovereign AI**: La capacidad de correr PII Guard en local te abre puertas en Gobierno y Banca que están cerradas para la competencia puramente Cloud.

### ⚠️ Amenazas y Debilidades
1.  **Guerra de Precios**: Los modelos de IA son cada vez más baratos (tendencia a cero). El margen que ganas haciendo "Arbitraje" se reducirá con los años. Deberás pivotar hacia "Observabilidad" y "Seguridad" como valor principal.
2.  **Latency Overhead**: Tu proxy añade latencia (PII check + DB call + RL). Debes mantenerla por debajo de 200ms o los desarrolladores se quejarán de que tu proxy es "lento".

---

*Documentación generada para ayudar en la comprensión profunda del código, sus riesgos y sus genialidades.*
