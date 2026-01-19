# 10. Auditoría Forense y "Modo CSI" (Forensic Replay)

> **Estado**: ✅ Implementado
> **Versión**: 1.0 (Enterprise Grade)

AgentShield introduce una capacidad única en el mercado de proxys IA: la **Reconstrucción Forense de Incidentes**. 
A diferencia de los logs tradicionales que solo muestran "qué pasó", nuestro sistema permite reconstruir "por qué pasó" y visualizar la cadena de custodia completa de una decisión.

## 1. Arquitectura de Trazabilidad (`trace_id`)

Para lograr una auditoría perfecta, hemos inyectado un "ADN digital" en cada petición.

### El Ciclo de Vida del `trace_id`
1.  **Nacimiento**: En `proxy.py`, antes de procesar nada, se genera un UUID único (`trc_xxxx`).
2.  **Propagación**:
    *   **Identidad**: Se asocia al usuario y departamento.
    *   **Política**: Se inyecta en los metadatos del `PolicyEngine` para saber qué reglas se evaluaron.
    *   **Herramientas**: Se inyecta oculto en los argumentos de las herramientas (`_trace_id`) para rastrear ejecuciones externas.
    *   **Facturación**: Se guarda en la tabla `receipts`.
    *   **Cliente**: Se devuelve en el header `X-AgentShield-Trace-ID`.

---

## 2. El Servicio Forense (`forensics.py`)

Este servicio actúa como un "arqueólogo de datos". Cuando se solicita una auditoría, no lee un log plano; consulta múltiples fuentes de verdad para reconstruir la historia.

### Fuentes de Datos Agregadas
1.  **Receipts**: El final de la transacción (coste, modelo usado, firma criptográfica).
2.  **Policy Events**: Los intentos de bloqueo, las reglas activadas y los modos "Shadow".
3.  **Tool Approvals**: Las intercepciones de herramientas, y si hubo intervención humana (aprobación/rechazo).
4.  **Security Events**: Intentos de Prompt Injection o fugas de PII detectadas.

### Generación de Evidencia Legal (PDF)
El sistema incluye un motor de generación de documentos (`fpdf2`) que crea un informe PDF descargable.
*   **Contenido**: Línea de tiempo cronológica, hash de los datos, y metadatos de seguridad.
*   **Validez**: Diseñado para ser presentado como evidencia de cumplimiento ("Chain of Custody") en auditorías externas o procesos legales.

---

## 3. Visualización en Dashboard (CSI Mode)

El frontend (`dashboard/receipts/[traceId]`) renderiza esta información en una interfaz intuitiva.

### Componentes Visuales
*   **Línea de Tiempo Vertical**: Inspirada en el tracking de paquetería, muestra el flujo paso a paso.
*   **Iconografía Semántica**:
    *   🛡️ Naranja: Chequeo de Política.
    *   🔒 Rojo: Interceptación de Herramienta o Alerta de Seguridad.
    *   ✅ Verde: Finalización exitosa.
    *   👁️ Azul: Revisión Humana.
*   **Caja Negra (JSON)**: Permite inspeccionar los datos crudos de cada paso para depuración técnica.

---

## Cómo Usar (Manual de Operación)

1.  **Identificar el Incidente**: En el reporte de gastos o logs, busca una transacción sospechosa y copia su `Trace ID`.
2.  **Abrir la Caja Negra**: Navega a `/dashboard/receipts/<TRACE_ID>`.
3.  **Analizar**: Revisa qué reglas saltaron y por qué.
4.  **Exportar**: Haz clic en "Export Legal PDF" para descargar el informe firmado.
