# 🦾 El Director de Orquesta: Tool Governor (Deep Dive)

El `ToolGovernor` es el componente más avanzado de AgentShield. Es el responsable de implementar la **Gobernanza de Agentes**, asegurando que la IA no realice acciones en el mundo real que no hayan sido autorizadas o que violen las políticas corporativas.

---

## 🎯 El Problema: El "Agente Desbocado" (Shadow Agent)
Cuando le das herramientas a una IA (como acceso a Internet, ejecución de código o APIs bancarias), el riesgo aumenta exponencialmente. Un modelo de IA puede, por un error de lógica o una instrucción ambigua, intentar realizar una acción irreversible o costosa.

El `ToolGovernor` actúa antes de que la acción ocurra, utilizando el principio de **Privilegio Mínimo** y la **Regla de Dos Hombres (2-Man Rule)**.

---

## 💎 Los Tres Niveles de Decisión

Cada vez que la IA intenta usar una "Tool", el gobernador evalúa:

### 1. ALLOW (Acceso Libre)
La acción es segura y está dentro de los límites del rol del usuario.
- **Ejemplo:** Un desarrollador ejecutando un `git status`.
- **Acción:** La llamada pasa al sistema sin interrupciones.

### 2. BLOCK (Prohibición Total)
La acción viola una política fundamental de la empresa o el usuario no tiene rango suficiente.
- **Ejemplo:** Un becario intentando acceder a la base de datos de salarios.
- **Acción:** Interceptamos la llamada y devolvemos un error al LLM explicándole que esa acción está **prohibida por política corporativa**.

### 3. REQUIRE_APPROVAL (La Regla de Dos Hombres / 2-Man Rule)
La acción es de alto riesgo pero permitida bajo supervisión.
- **Ejemplo:** Una transferencia bancaria de más de $5,000.
- **Acción:** Pausamos la ejecución, creamos un registro de aprobación en el dashboard y le notificamos al LLM (y al usuario) que la acción está **pendiente de autorización por un supervisor**. La IA queda en espera.

---

## 🛠️ Inteligencia Política Dinámica

A diferencia de los sistemas rígidos, el `ToolGovernor` es **data-driven**. Las reglas viven en la base de datos (`tool_policies`) y pueden ser editadas sin tocar el código:
- **Filtrado por Rol y Departamento:** Diferentes reglas para RRHH que para IT.
- **Argument Rules:** Reglas basadas en el contenido de la llamada (ej. bloquear si `amount > 500`).
- **Audit Table (`tool_approvals`):** Registro inmutable de cada solicitud de acción.

---

## 📈 Impacto en el Negocio
- **Adopción de Agentes Segura:** Permite desplegar trabajadores de IA autónomos con la tranquilidad de que nunca harán nada "loco".
- **Cumplimiento Corporativo:** Garantiza que cada acción importante tenga un rastro de auditoría y, opcionalmente, una firma humana.
- **Prevención de Pérdidas:** Evita errores costosos en sistemas críticos.

**Tool Governor es el volante y el freno que permite que los Agentes de IA conduzcan el negocio hacia el futuro.**
