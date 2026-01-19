# 👁️ Módulo 5: Observabilidad y Analytics (`The Eye`)

> **Foco**: Visibilidad Total, Telemetría y Sostenibilidad (Green AI).
> **Archivos Clave**: `app/routers/analytics.py`, `app/main.py`, `app/routers/dashboard.py`.

---

## 1. Filosofía: "No puedes mejorar lo que no mides"
En sistemas de IA, "funciona" no es suficiente. Necesitas saber:
*   ¿Cuánto estoy gastando por segundo?
*   ¿Qué cliente me está consumiendo más tokens?
*   ¿Cuántos árboles estoy plantando gracias a la eficiencia energética?

---

## 2. OpenTelemetry (OTEL) en `app/main.py`
No usamos logs de texto plano antiguos. Usamos **Traza Distribuida**.

### Implementación
En `setup_observability` (líneas 74-100 de `main.py`):
1.  **Instrumentación Automática**: `FastAPIInstrumentor` espía cada petición HTTP sin que escribas código.
2.  **Exportador OTLP**: Envía las métricas a cualquier backend compatible (Grafana Cloud, Datadog, Honeycomb) usando `OTLPSpanExporter`.
3.  **Beneficio**: Puedes ver un "Flame Graph" que te dice exactamente que la petición tardó 200ms en total: 10ms en PII, 5ms en Redis y 185ms esperando a OpenAI.

---

## 3. Green AI / Sostenibilidad (`app/routers/analytics.py`)
La IA consume mucha energía. Las empresas necesitan reportar su huella de carbono (ESG).

### Endpoint: `/v1/analytics/sustainability`
Calculamos el CO2 emitido por cada token procesado basándonos en:
1.  **Región del Servidor**: No es lo mismo correr en Suecia (Hydro) que en Virginia (Carbón). Detectamos la región en `verify_residency`.
2.  **Modelo Usado**: GPT-4 consume ~10x más energía que Llama-3-8b.
3.  **Certificado de Ahorro**: Gracias al Arbitraje (usar modelos pequeños cuando es posible), generamos un reporte de "Emisiones Evitadas" que el cliente puede poner en su web corporativa.

---

## 4. Dashboard en Tiempo Real (`app/routers/dashboard.py`)
Para el usuario humano.
*   **Stats Vivas**: Consulta Redis para ver contadores atómicos (`incrbyfloat`).
*   **FOMO (Fear Of Missing Out)**: Muestra gráficas de "Ahorro Potencial" si el cliente no tiene activo el arbitraje, incentivando el upgrade.

---

## 5. Resumen de Decisiones (Pros/Contras)

| Decisión | Por qué es brillante (Pros) | Riesgo (Contras) |
| :--- | :--- | :--- |
| **OpenTelemetry Nativo** | Estándar de la industria. No nos ata a ningún vendedor de logs. | Configuración inicial compleja (endpoint, headers, proto). |
| **Metricas de CO2** | Diferenciador de venta único para clientes Enterprise/ESG. | La estimación de carbono es aproximada, no científica exacta (depende del mix energético real del momento). |
| **Logs Asíncronos** | La API nunca se bloquea escribiendo logs. | Si el servidor crashea violentamente, los últimos logs en memoria (Queue) podrían perderse. |
