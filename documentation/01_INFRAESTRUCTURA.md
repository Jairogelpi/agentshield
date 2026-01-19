# 🏗️ 01. Infraestructura y Arquitectura General

> **Visión Global**: Cómo diseñamos un sistema de IA Enterprise para correr en una "patata" (2GB RAM / 1 CPU).
> **Objetivo**: Eficiencia Extrema, Latencia Mínima y Seguridad Zero-Trust.

---

## 1. El Desafío: "Constraints-First Design"
La mayoría de SaaS de IA queman dinero en servidores GPU masivos. AgentShield hace lo contrario.
*   **Hardware Objetivo**: Render Free/Starter Tier (o AWS t4g.small).
*   **Recursos**: 512MB - 2GB RAM, 0.5 - 1 CPU Core.
*   **Requisito Latencia**: < 200ms overhead sobre la llamada a OpenAI.

Para lograr esto, no pudimos usar frameworks pesados (Django, Celery). Tuvimos que ingeniería híbrida.

### La Solución Híbrida (Python + Rust)
No es 100% Python. Las partes críticas corren en código nativo compilado.

| Componente | Tecnología | Por qué |
| :--- | :--- | :--- |
| **Servidor Web** | `Granian` (Rust) | Maneja HTTP/2 y WebSockets con un loop más eficiente que Uvicorn. |
| **Lógica Negocio** | `FastAPI` (Python) | Velocidad de desarrollo y ecosistema de IA. |
| **PII Scrubbing** | `Rust Regex` | Escanear 1MB de texto en Python bloquea la CPU 50ms. En Rust, 0.5ms. |
| **Caching** | `Redis` (Memory) | Persistencia volátil ultrarrápida (Cache, Rate Limit). |
| **Persistencia** | `Supabase` (SaaS) | Delegamos la DB pesada (PostgreSQL) para no gastar CPU local. |

---

## 2. Arquitectura de Despliegue

```mermaid
graph TD
    User[Cliente SaaS] -->|HTTPS| CF[Cloudflare WAF]
    CF -->|Zero-Trust Header| Server[AgentShield (Render/K8s)]
    
    subgraph "AgentShield Pod (2GB RAM)"
        Server -->|Auth Check| Redis[(Redis Cache)]
        Server -->|PII Scan| RustCore[Rust Module]
        Server -->|Router| Proxy[Universal Proxy]
    end
    
    Proxy -->|Cache Hit?| Redis
    Proxy -->|No Hit| Arbitraje[RL Arbitrage Engine]
    Arbitraje -->|Selección| LiteLLM[LiteLLM Gateway]
    
    LiteLLM -->|API Call| OpenAI[OpenAI / Anthropic]
    LiteLLM -->|API Call| Local[Ollama / LocalAI]
```

---

## 3. Estructura de Documentación Detallada
Para entender cada tornillo, revisa los "Deep Dives":

*   **[01.1 Dockerfile y Build](01.1_INFRA_DOCKER.md)**: Cómo logramos imágenes de 150MB con modelos pre-cargados.
*   **[01.2 Núcleo Rust](01.2_INFRA_RUST.md)**: Explicación del código `lib.rs` y la integración PyO3.
*   **[01.3 Dependencias](01.3_INFRA_DEPENDENCIAS.md)**: Por qué elegimos cada librería en `requirements.txt`.

---

## 4. Filosofía "Stateless"
El servidor no guarda estado en memoria entre peticiones (excepto modelos cargados en Read-Only).
*   **Si se reinicia el servidor**: No se pierde nada (todo está en Redis/Supabase).
*   **Escalado**: Puedes levantar 50 réplicas del contenedor y todas compartirán el conocimiento (Limitador de Velocidad global, Caché global).

---

## 5. Secret Management (Vault Virtual)
No guardamos claves API en la DB.
*   Las claves maestras (OpenAI, Anthropic) se inyectan como Variables de Entorno en el despliegue.
*   El código usa `app.services.vault.get_secret()` para recuperarlas en tiempo de ejecución de forma segura.
