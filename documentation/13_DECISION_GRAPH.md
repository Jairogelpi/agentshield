# 13. Decision Graph: AgentShield Core Engine 🧠

AgentShield opera mediante un **Decision Graph** de 9 etapas que garantiza que cada token generado esté gobernado por identidad, riesgo, política y economía.

## Las 9 Estapas del Ciclo de Vida

```mermaid
graph TD
    A[1. Identity Envelope] --> B[2. Context Builder]
    B --> C[3. Intent Classifier]
    C --> D[4. Risk Engine]
    D --> E[5. Policy Engine]
    E --> F[6. Knowledge Pricing]
    F --> G[7. Execution Router]
    G --> H[8. Receipt Writer]
    H --> I[9. Ledger Settlement]
```

### 1. Identity Envelope (JWT/SSO)
- **Función**: Verifica la autenticidad del emisor usando firmas RSA.
- **Implementación**: `verify_identity_envelope` in `identity.py`.

### 2. Context Builder
- **Función**: Reúne metadatos del `tenant`, `user`, `dept` y `cost_center`.
- **Implementación**: Clase `AgentShieldContext` en `schema.py`.

### 3. Intent Classifier (Semantic Budgeting)
- **Función**: Clasifica la intención (ej: `LEGAL`, `CODING`) para detectar desviaciones de rol.
- **Implementación**: `semantic_router.classify_intent` in `semantic_router.py`.

### 4. Risk Engine (Trust Score)
- **Función**: El "Corazón Moral". Evalúa el `Trust Score` (0-100) en Redis.
- **Lógica**: 
    - Si el score es `< 70`, el sistema aplica un `Downgrade` silencioso a modelos más baratos/seguros.
    - Si el score es `< 30`, el sistema activa el modo `Supervised` bloqueando la respuesta.
- **Implementación**: `trust_system.py`.

### 5. Policy Engine
- **Función**: Barrera binaria (BLOCK/ALLOW) y sanitización PII dinámica.
- **Feedback Loop**: Cada violación detectada por el Policy Engine dispara un castigo de `-5` a `-10` puntos en el Risk Engine.
- **Implementación**: `evaluate_policies` in `policy_engine.py`.

### 6. Knowledge Pricing (Internal Economy)
- **Función**: Si se usa RAG, verifica licencias y cobra micro-pagos internos entre departamentos.
- **Liquidación**: Los pagos se registran en el `internal_ledger`.
- **Implementación**: `marketplace.py`.

### 7. Execution Router
- **Función**: Arbitraje multimodelo con resiliencia y circuit breaking.
- **Implementación**: `execute_with_resilience` in `llm_gateway.py`.

### 8. Receipt Writer (Forensic Web)
- **Función**: Firma criptográficamente el resultado y el hash de las políticas aplicadas.
- **Implementación**: `create_forensic_receipt` in `receipt_manager.py`.

### 9. Ledger Settlement (CFO Brain)
- **Función**: Liquidación atómica en Redis y persistencia en el `reputation_ledger`.
- **Implementación**: `charge_hierarchical_wallets` in `limiter.py`.

---
**AgentShield OS: Control Total sobre el Caos de la IA.**
