# 🕵️ Deep Dive: El Investigador Forense (`forensics.py`)

Si `audit.py` guarda las llaves, `forensics.py` es el archivo que **abre la Caja Negra** cuando algo sale mal. Es la herramienta definitiva para los CISO y equipos de seguridad para entender qué pasó exactamente durante un incidente.

---

## 1. ¿Qué hace este archivo? (El Propósito)
Permite reconstruir la vida completa de una petición específica (identificada por su `trace_id`). Si un empleado intenta fugar secretos de la empresa o si la IA responde algo peligroso, este archivo es el que permite ver la película completa de los hechos.

## 2. Los 3 Pilares del Valor de Negocio

### No. 1: Replay de Incidentes (Timeline Reconstruction)
El sistema no solo guarda el "input" y el "output". Reconstruye cada paso intermedio:
*   **Valor:** Permite ver: "¿Qué rol tenía el usuario?", "¿Qué filtro de PII saltó?", "¿Cómo cambió el Trust Score en ese segundo?". Es la diferencia entre tener una foto borrosa y tener un vídeo en 4K del incidente.

### No. 2: Cadena de Custodia (Legal PDF Export)
Genera automáticamente un PDF diseñado para ser admisible en un juicio o proceso de Recursos Humanos.
*   **Valor:** Ahorra semanas de trabajo manual al equipo legal. El PDF incluye marcas de tiempo precisas y la firma digital del sistema, garantizando que la evidencia es pura y no ha sido manipulada.

### No. 3: Auditoría por Trace ID
Gracias a la observabilidad que implementamos en el middleware, este router puede unir piezas de diferentes microservicios usando el `X-Request-ID`.
*   **Valor:** Permite una trazabilidad total "End-to-End". Es el sueño de cualquier analista de seguridad.

---

## 3. ¿Dónde se usa y cómo se integra?
*   **Centro de Operaciones de Seguridad (SOC):** Cuando AgentShield detecta una anomalía de gasto o de seguridad, el analista hace clic en "Investigar" y este router le sirve la información.
*   **Reportes de RRHH:** Se usa para justificar acciones disciplinarias basadas en el uso indebido de la IA.

## 4. ¿Cómo podría mejorar? (God Tier Next Steps)
1.  **AI Reconstruction Summary:** Usar una IA "Soberana" interna para leer el timeline y dar un resumen ejecutivo: *"El usuario intentó extraer el plan de marketing usando una técnica de Inyección de Prompt conocida como 'Grandma's secret recipe'"*. 
2.  **Visual Timeline (Mermaid):** Exportar el timeline no solo en texto, sino como un diagrama de secuencia visual para el dashboard.
3.  **Cross-Incident Correlation:** Sugerir otros `trace_id` que se parezcan a este incidente para detectar patrones de ataque.

**Este archivo transforma a AgentShield de un simple filtro a una herramienta de defensa activa. Es el seguro de vida de la empresa contra el mal uso de la IA.**
