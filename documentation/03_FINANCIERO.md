# 💰 Módulo 3: El Motor Financiero (`The CFO`)

> **Foco**: Rentabilidad, Arbitraje de IA en tiempo real y Auditoría de Costes.
> **Archivos Clave**: `app/services/arbitrage.py`, `app/services/pricing_sync.py`, `app/estimator.py`.

---

## 1. El Concepto: "La Bolsa de Valores de Modelos"
En lugar de ver los precios de IA como fijos, AgentShield los trata como un **Mercado Fluido**. Los precios de OpenAI, Anthropic y Llama cambian, y tu sistema debe reaccionar.

---

## 2. El Protocolo Espejo (`app/services/pricing_sync.py`)
Antes de calcular nada, necesitamos saber la verdad del mercado.

### ¿Cómo funciona?
Al arrancar (`startup_event` en `main.py`), este servicio:
1.  **Consulta LiteLLM**: Extrae los precios "duros" de la librería.
2.  **Consulta OpenRouter API**: Descarga precios de modelos nuevos que LiteLLM aun no conoce (ej. un modelo salido hace 1 hora).
3.  **Sincronización Redis**: Guarda todo en Redis (`price:gpt-4`) para acceso en O(1) tiempo (microsegundos).
4.  **Auditoría en Vivo**: Si durante una llamada, LiteLLM nos dice que el coste fue bajó, pero nuestra DB dice alto, `audit_and_correct_price` se dispara y corrige el precio en tiempo real.

---

## 3. El Árbitro Inteligente (`app/services/arbitrage.py`)
Aquí es donde ocurre la magia del ahorro.

### Lógica de Reinforcement Learning (RL)
Usamos un algoritmo de "Bandido Contextual" (`AgentShieldRLArbitrator`):

1.  **Análisis de Prompt**: Un juez IA interno lee tu prompt y le asigna una complejidad (0-100).
    *   *Ejemplo*: "Hola" -> Complejidad 5.
    *   *Ejemplo*: "Resume este contrato legal" -> Complejidad 90.
2.  **Consulta Q-Table**: Mira en Redis qué modelo ha dado mejor resultado (ROI) para esa complejidad históricamente.
    *   Para complejidad 5, probablemente `Llama-3-8b` tiene mejor ROI que `GPT-4`.
3.  **Acción**: El Proxy cambia el modelo transparentemente. El usuario pidió GPT-4, pero recibe una respuesta de Llama-3 (que es igual de buena para decir "Hola") y se ahorra un 98% del coste.

### Métricas FOMO (Fear Of Missing Out)
Si el arbitraje estaba apagado, calculamos `missed_savings`: "Podrías haber ahorrado $500 hoy si hubieras activado AgentShield".

---

## 4. Estimador Multimodal (`app/estimator.py`)
No solo contamos tokens. El sistema entiende precios complejos:
*   **Imágenes**: Calcula el precio de DALL-E 3 basándose en la resolución (1024x1024 vs HD).
*   **Audio**: Calcula el precio de Whisper por segundo.
*   **Feedback Loop**: `learn_from_reality` hace que el estimador ajuste sus ratios Input/Output basándose en el tráfico real del cliente.

---

## 5. Resumen de Decisiones (Pros/Contras)

| Decisión | Por qué es brillante (Pros) | Riesgo (Contras) |
| :--- | :--- | :--- |
| **Active Arbitrage** | Convierte el Gateway en un centro de beneficios (Profit Center). Se paga solo. | Si el modelo "barato" alucina, el usuario final puede notarlo. Requiere ajuste fino del umbral de calidad. |
| **Mirror Protocol** | Nunca perdemos dinero por tener precios desactualizados. | Dependemos de que la API de OpenRouter esté arriba para modelos nuevos. |
| **Redis Pricing** | Cálculo de costes sin latencia de DB. | Si Redis se vacía, hay que rehidratarlo desde DB, lo que añade 100ms la primera vez. |
