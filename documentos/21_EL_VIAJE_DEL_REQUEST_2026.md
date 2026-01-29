# 🚀 El Viaje del Request 2026: Arquitectura de Conexión Total

Este documento describe la secuencia exacta de eventos desde que un usuario o agente lanza un prompt hasta que recibe el "HUD Protocol" con la respuesta blindada. Es el diagrama maestro para entender el **Absolute Zenith** de AgentShield.

---

## ⚡ Diagrama de Secuencia Maestro (Mermaid)

```mermaid
sequenceDiagram
    participant U as Usuario / Agente
    participant EDGE as Cloudflare (Edge)
    participant MID as Middlewares (Sensors)
    participant RT as Router (Proxy/Auth)
    participant DP as Decision Pipeline (Gates)
    participant LLM as Providers (OpenAI/Anthropic)
    participant SIEM as Event Bus / SIEM

    U->>EDGE: Request HTTPS (Prompt)
    EDGE->>MID: Forward with X-AgentShield-Auth
    
    Note over MID: Nivel 1: security_guard_middleware
    MID->>SIEM: Signal: REQUEST_RECEIVED (trace_id)
    
    Note over MID: Nivel 2: global_security_guard
    alt API Key Inválida
        MID->>SIEM: Signal: AUTH_FAILURE (Critical)
        MID-->>U: HTTP 401 Unauthorized
    else Brute Force Detectado
        MID->>SIEM: Signal: BRUTE_FORCE_BLOCKED (Critical)
        MID-->>U: HTTP 429 Too Many Requests
    end

    MID->>RT: Autenticación OK (tenant_id inyectado)
    
    RT->>DP: process_request(DecisionContext)
    
    Note over DP: Gate 1: Intent & Trust Scoring
    Note over DP: Gate 2: PII Redaction (Rust)
    DP->>SIEM: Signal: PII_DETECTED (si aplica)
    
    Note over DP: Gate 3: Arbitrage & Budget Check
    
    DP->>LLM: Inferencia Segura (acompletion)
    LLM-->>RT: Stream de Respuesta
    
    Note over RT: ObserverService: Audit de Respuesta
    RT->>SIEM: Signal: ETHICS_POLICY_ALERT (si hay sesgo/alucinación)
    
    RT->>SIEM: Signal: LLM_TRANSACTION_COMPLETE
    
    RT-->>U: Stream + HUD Protocol (Collective Wisdom)
```

---

## 💎 Los 3 Momentos de la Verdad

### 1. El Momento de la Defensa (Middleware)
Antes de que AgentShield gaste 1ms de CPU en IA, los middlewares actúan como **sensores sísmicos**. 
*   **Valor:** La empresa sabe que está siendo atacada o escaneada **antes** de que el ataque tenga éxito, gracias a las señales enviadas al SIEM en este nivel.

### 2. El Momento de la Decisión (Pipeline)
Aquí es donde ocurre la magia técnica. El `DecisionContext` es la "Caja Negra" que registra por qué se eligió un modelo u otro, qué datos se redactaron y qué riesgo se asumió.
*   **Valor:** Trazabilidad absoluta. Cada `trace_id` permite reconstruir por qué una respuesta costó $0.002 en lugar de $0.02.

### 3. El Momento de la Verdad (Observer & HUD)
La respuesta no se entrega a ciegas. El `ObserverService` audita la IA mientras el usuario lee. 
*   **Valor:** El HUD Protocol no es solo estética; es **transparencia radical**. El usuario ve el score de veracidad y el ahorro en tiempo real, reforzando el valor de la plataforma con cada palabra.

---

## 📈 Conclusión
Esta arquitectura de **"Señalización Continua"** convierte a AgentShield en un sistema que no solo protege, sino que **aprende y comunica**. En 2026, la seguridad es visibilidad, y este flujo de vida garantiza que la empresa siempre tenga el control total del viaje de sus datos.
