# 🛡️ Deep Dive: El Guardián de la Reputación (`trust.py`)

Si AgentShield fuera un aeropuerto, `trust.py` sería el **Control de Inmigración Inteligente**. No trata a todo el mundo igual; sabe quién es de confianza y quién tiene un historial de "comportamiento arriesgado".

---

## 1. ¿Qué hace este archivo? (El Propósito)
Gestiona el **Trust Score** (Puntuación de Confianza) de cada usuario individual. Su función estrella es la "Válvula de Amnistía", que permite a un usuario recuperar el acceso a modelos de IA potentes tras haber cometido errores (como intentar enviar datos sensibles).

## 2. Los 3 Pilares del Valor de Negocio

### No. 1: Seguridad Adaptativa (Contextual Security)
En lugar de bloquear a un usuario para siempre, AgentShield degrada su experiencia. Si el score baja de 70, el Proxy le impide usar modelos "Premium" (ej. GPT-4), forzándolo a usar modelos más controlados.
*   **Valor:** No detiene la productividad, pero minimiza el riesgo de que un usuario "no confiable" maneje modelos de alta capacidad que podrían ser más fáciles de manipular.

### No. 2: La Válvula de Amnistía (Education Over Punishment)
Permite que un usuario "limpie su historial" reconociendo formalmente las políticas de seguridad.
*   **Valor:** Fomenta la **Cultura de Seguridad**. En lugar de ser un sistema punitivo ciego, AgentShield educa al usuario. Una vez que el usuario confirma que entiende las reglas, el sistema le devuelve el voto de confianza.

### No. 3: Gamificación de la Seguridad
El sistema permite rastrear quiénes son los usuarios más seguros de la empresa.
*   **Valor:** Permite a RRHH o Seguridad premiar los buenos comportamientos, convirtiendo la ciberseguridad en algo positivo y medible, no solo en restricciones.

---

## 3. ¿Dónde se usa y cómo se integra?
*   **Proxy Integration:** El Proxy consulta el score antes de elegir el modelo de IA.
*   **Portal del Empleado:** Cuando un empleado ve que no puede acceder a una función, el portal le redirige a `acknowlege-training` para recuperar su score.

## 4. ¿Cómo podría mejorar? (God Tier Next Steps)
1.  **Dynamic Training:** Que el entrenamiento que el usuario debe reconocer sea dinámico basado en su error específico (ej. si falló en PII, mostrarle un vídeo sobre protección de datos).
2.  **Trust-Based Pricing:** Cobrar menos (markup menor) a los usuarios con score alto, ya que suponen menos riesgo y menos coste de auditoría para la empresa.
3.  **Peer Review:** Permitir que un manager "avalé" manualmente a un empleado para subir su score tras una revisión personal.

**Este archivo es el que "humaniza" la seguridad de AgentShield. Convierte un sistema de reglas rígidas en una relación de confianza dinámica con el empleado.**
