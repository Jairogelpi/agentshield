# 🛡️ Deep Dive: El Escudo Legal (`compliance.py`)

Si el Proxy es el motor, `compliance.py` es el **Oficial de Cumplimiento (DPO)** de AgentShield. Es el archivo que asegura que la empresa no infrinja leyes como el GDPR o el nuevo EU AI Act.

---

## 1. ¿Qué hace este archivo? (El Propósito)
Proporciona las herramientas necesarias para que los administradores y auditores gestionen el riesgo legal. Permite borrar datos privados, generar informes oficiales y resolver dudas de seguridad que la IA no pudo decidir por sí sola.

## 2. Los 4 Pilares del Valor de Negocio

### No. 1: El Protocolo "Derecho al Olvido" (GDPR Compliance)
Permite anonimizar todas las peticiones de un usuario específico manteniendo los registros financieros intactos.
*   **Valor:** Cumple con el requisito más duro del GDPR sin romper la contabilidad de la empresa. Ejecuta una purga de datos sensibles rápida y certificada.

### No. 2: Certificados de Auditoría (AI Act Ready)
Genera "Snapshots" y reportes en PDF que sirven como evidencia legal ante reguladores.
*   **Valor:** En caso de una auditoría externa, la empresa puede descargar un certificado firmado que demuestra que AgentShield ha estado supervisando, filtrando y auditando cada token de IA.

### No. 3: La Cuarentena HITL (Human-in-the-loop)
Cuando la IA de seguridad tiene dudas sobre si un contenido es peligroso, lo envía a una "Cola de Cuarentena".
*   **Valor:** Permite que un experto humano tome la decisión final. Esto evita "falsos positivos" que bloqueen el trabajo legítimo de los empleados.

### No. 4: Aprendizaje Activo (Active Learning)
Cuando un humano libera un archivo de la cuarentena, el sistema aprende. El hash del archivo aprobado entra en una `semantic_whitelist`.
*   **Valor (Ahorro):** La próxima vez que alguien use ese mismo documento, el sistema lo reconocerá al instante (latencia 0ms) sin gastar tokens en volver a analizarlo.

---

## 3. ¿Dónde se usa y cómo se integra?
*   **Dashboard del DPO:** Es la base de la pestaña de "Legal/Compliance" en el panel de control.
*   **Auditoría Externa:** Los enlaces generados aquí son los que se entregan a auditores de ISO 27001 o reguladores gubernamentales.

## 4. ¿Cómo podría mejorar? (God Tier Next Steps)
1.  **Integración GRC:** Conectar automáticamente estos informes con herramientas como Vanta o Drata para automatizar la certificación SOC2.
2.  **Alertas de Deriva Legal:** Notificar si el perfil de uso de la empresa cambia de "Riesgo Bajo" a "Riesgo Alto" según el EU AI Act.
3.  **Análisis de Sesgo (Bias Check):** Integrar reportes automáticos que certifiquen que la IA no está dando respuestas sesgadas o discriminatorias.

**Este archivo es el que permite que el CEO y el equipo Legal duerman tranquilos. Convierte una tecnología "salvaje" como la IA en un activo corporativo controlado y legalmente seguro.**
