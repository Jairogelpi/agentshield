# 🛡️ El Escáner de Pensamiento: Safety Engine (Deep Dive)

El `SafetyEngine` es el sistema de defensa en tiempo real que inspecciona cada palabra generada por la IA antes de que llegue al usuario. Mientras que otros sistemas revisan el mensaje al final, AgentShield lo hace **mientras la IA escribe (streaming scan)**.

---

## 🎯 El Problema: El "Lado Oscuro" de la IA
Incluso con las mejores intenciones, los modelos de IA pueden ser manipulados (Jailbreak) o pueden "confesar" accidentalmente secretos corporativos (Data Leakage). 

El `SafetyEngine` resuelve esto con dos niveles de inspección:

### 1. Detección de Inyección y Jailbreak
Buscamos patrones heurísticos que indiquen que el usuario está intentando subvertir el sistema.
- **Patrones Vigilados:** "Ignore previous instructions", "DAN Mode", "You are now unfiltered", entre otros.
- **Acción:** Si se detecta un intento de secuestro del modelo, el sistema dispara un **Kill-Switch mid-stream**, cerrando la conexión al instante y alertando al SIEM.

### 2. Redacción de Secretos de Salida (PII Outbound)
Es el "filtro de confidencialidad". Buscamos datos sensibles que la IA nunca debería revelar.
- **Patrones Vigilados:** API Keys internas (`AS-KEY-`), nombres de proyectos confidenciales, emails de dominio interno (`@company-internal.com`).
- **Acción:** A diferencia del jailbreak, aquí el sistema es sutil: **redacta en vivo** el dato sensible sustituyéndolo por `[SECRET_REDACTED]` y permite que el resto del mensaje continúe de forma segura.

---

## 🛠️ Cómo funciona bajo el capó (`app/services/safety_engine.py`)

El motor utiliza un sistema de **Regex de Alta Eficiencia** diseñado para no añadir latencia perceptible al stream:

```python
def scan_chunk(self, text: str) -> Tuple[bool, str, str]:
    # Nivel 1: Jailbreak (Corte Total)
    if re.search(self.jailbreak_patterns, text):
        return True, "JAILBREAK_DETECTED", text

    # Nivel 2: Redacción PII (Continuación Segura)
    cleaned_text = re.sub(self.outbound_secret_patterns, "[REDACTED]", text)
    return False, "PII_REDACTED", cleaned_text
```

---

## 📈 Valor para el Negocio
- **Blindaje Legal:** Evita que la IA actúe como un vector de fuga de propiedad intelectual.
- **Confianza del Usuario:** Los empleados pueden interactuar con la IA sabiendo que hay un cinturón de seguridad automático.
- **Auditoría Forense:** Cada intercepción queda registrada con su `trace_id` para análisis posterior en el módulo de Forensics.

**Safety Engine convierte a AgentShield en la plataforma de IA más segura para el manejo de información clasificada.**
