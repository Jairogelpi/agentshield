# 🚀 Deep Dive: El Motor de Proxy (`proxy.py`)

Este archivo es el componente más importante de AgentShield. Es el que recibe las peticiones de chat (estilo OpenAI) y las procesa a través de todas las capas de seguridad antes de enviarlas a la IA real.

---

## 1. ¿Qué hace este archivo?
Es el **Orquestador Principal**. Cuando un usuario envía un mensaje ("Hola, ¿cómo estás?"), el Proxy no responde de inmediato. Primero lo pasa por el "Decision Pipeline" (la tubería de decisiones) para ver:
*   ¿Quién es el usuario?
*   ¿Qué rol tiene?
*   ¿Tiene presupuesto?
*   ¿Su mensaje tiene datos sensibles (PII)?
*   ¿Es una pregunta que ya respondimos antes? (Ahorro de caché).

## 2. Las 3 Joyas de la Corona

### No. 1: Hive Memory (Caché Semántico)
Antes de gastar dinero en la IA (OpenAI/Anthropic), el proxy mira en la **Memoria Colmena (Hive)**.
*   **Si ya sabemos la respuesta:** La servimos instantáneamente desde Redis.
*   **Valor:** Ahorro total del 100% en esa petición y latencia de milisegundos.

### No. 2: El HUD (Heads-Up Display) en Tiempo Real
Esta es la característica visual más potente. Mientras la IA escribe, el Proxy inyecta "metadatos" invisibles que el frontend usa para mostrar una tarjeta al final de la respuesta.
*   **Métricas inyectadas:** Latencia, Tokens, Costos, **Ahorros**, Huella de CO₂ y Nivel de Confianza (Trust Score).

### No. 3: Blindaje de Salida (Post-Processing)
Una vez que la IA responde, el Proxy no se detiene.
*   **Firma el recibo:** Crea una prueba criptográfica de lo que pasó.
*   **Aprende:** Si la respuesta fue buena y costosa, la guarda en la Memoria Colmena para el futuro.

## 3. Valor para el Producto Final
Es lo que transforma una simple llamada a una API en una **Transacción Corporativa Blindada**. Da transparencia total al usuario sobre cuánto está ahorrando y asegura que la empresa tenga control absoluto sobre cada token.
