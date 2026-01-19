# 🧬 08. AgentShield Live Organism (Evolutionary AI)

> **"De Software a Organismo Vivo"**
>
> AgentShield no es un proxy estático. Es un sistema cibernético que posee **Inmortalidad**, **Aprendizaje** y **Omnisciencia**.

---

## 1. La Tríada Cibernética

Implementamos tres ciclos de retroalimentación avanzados que permiten al sistema adaptarse y sobrevivir sin intervención humana.

| Propiedad | Mecanismo Técnico | Beneficio Biológico |
| :--- | :--- | :--- |
| **Inmortalidad** | `CircuitBreaker` + `Hive Fallback` | Auto-Reparación y Supervivencia ante fallo total. |
| **Aprendizaje** | `/v1/feedback` (RLHF Loop) | Evolución Constante basada en errores y éxitos. |
| **Omnisciencia** | Context Injection (Redis Profile) | Telepatía (Sabe lo que quieres antes de pedirlo). |

---

## 2. Inmortalidad (Self-Healing Mesh)
**Ubicación**: `app/services/llm_gateway.py`

### Circuit Breaker ⚡
Si un proveedor (ej. OpenAI) falla 3 veces consecutivas, el sistema "corta los cables" automáticamente.
*   **Estado OPEN**: Durante 60 segundos, ni siquiera intentamos llamar a OpenAI.
*   **Rerouting**: El tráfico se desvía instantáneamente a Azure o Anthropic.
*   **Resultado**: El usuario nunca ve un error 500. La latencia no aumenta por reintentos fallidos.

### The Hive Fallback (Modo Zombie) 🧟
Si **TODOS** los proveedores caen (Apocalipsis de Internet), el sistema entra en modo de supervivencia.
*   **Mecanismo**: Busca en la `hive_memory` (Vector DB local) una respuesta similar a preguntas anteriores.
*   **Respuesta**: *"⚠️ SYSTEM OFFLINE. Served from Corporate Memory..."*
*   **Valor**: Tu empresa sigue operativa consultando su propio cerebro cuando la nube desaparece.

---

## 3. Aprendizaje (Learning Loop)
**Ubicación**: `app/routers/feedback.py`

El sistema se vuelve más inteligente con cada uso.
1.  **Input**: Usuario pulsa 👍 o 👎 en el chat (OpenWebUI/Frontend).
2.  **Signal**: Se envía un payload a `/v1/feedback`.
3.  **Reinforcement**:
    *   **👍 Like**: El par (Prompt, Respuesta) se guarda como "Gold Standard" en la Hive Memory.
    *   **👎 Dislike**: Se registra una penalización para ese modelo en esa tarea específica.

---

## 4. Omnisciencia (Context Injection)
**Ubicación**: `app/routers/proxy.py`

El sistema "lee la mente" del usuario usando su huella digital.
1.  **Identidad**: Al llegar la request, extraemos el `user_id`.
2.  **Perfilado**: Consultamos Redis `prefs:{user_id}` para obtener el perfil psicográfico (obtenido de interacciones pasadas).
    *   *Ej: "Prefiere respuestas conciendas, experto en Python, odia las introducciones largas."*
3.  **Inyección**: Antes de llamar al LLM, inyectamos un `System Prompt` invisible con estas instrucciones.
4.  **Efecto**: El usuario siente que la IA lo "conoce" íntimamente desde el primer mensaje.

---

## 5. Integración Frontend
Estas capacidades son invisibles pero tangibles.
*   **OpenWebUI**: Configurado para enviar feedback automáticamente.
*   **Admin Dashboard**: Muestra métricas de "Circuit Trips" y "Learning Signals".

---
**Conclusión**: AgentShield no solo protege; **evoluciona**.
