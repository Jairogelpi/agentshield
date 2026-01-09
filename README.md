# 🛡️ AgentShield Core: Sovereign AI Gateway (v2026)

[![Rust](https://img.shields.io/badge/Built_with-Rust-orange?style=flat-square&logo=rust)](https://www.rust-lang.org/)
[![Python 3.13](https://img.shields.io/badge/Python-3.13_(No_GIL)-blue?style=flat-square&logo=python)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-God_Tier-8A2BE2?style=flat-square)](https://github.com/agentshield)

**AgentShield Core** is the world's first **Sovereign AI Gateway** designed for the post-2025 regulatory landscape. It is not just a proxy; it is a **Compliance Officer** and **Financial Hedge Fund** for your AI tokens.

---

## ⚡ Why This Has No Competitors?

Most gateways (Kong, LiteLLM, Helicone) are just "Middlemen". AgentShield is an **Active Guardian**.

| Feature | 🛡️ AgentShield (Sovereign) | ☁️ Cloudflare / Azure / Kong |
| :--- | :--- | :--- |
| **Privacy** | **Local ONNX PII Scrubbing** (Data never leaves RAM) | API-based (Data leaks to scrubbers) |
| **Performance** | **Rust + Python 3.13 (No-GIL)** | Standard Python/Go/Java |
| **Financials** | **Kalman Filter Arbitrage** (Predicts Latency/Prices) | Static Round-Robin |
| **Legal** | **Auto-Generated EU/US Compliance Certs (PDF)** | Logs only (You pay lawyers) |
| **Security** | **C2PA Content Provenance (Rust Signed)** | None |

---

## 🚀 Key Features

### 1. 🧠 Sovereign AI (Privacy First)
- **Hybrid PII Guard**: Uses a local quantized Small Language Model (SLM) running on ONNX Runtime within the container.
- **Benefits**: Your sensitive data (Credit Cards, Names, Secrets) is redacted **BEFORE** it hits OpenAI/Anthropic. zero external leakage.

### 2. 🦀 Rust Acceleration (`agentshield_rust`)
- CPU-bound tasks are offloaded to native compiled Rust:
    - **Zero-Copy Image Signing**: C2PA metadata injection for images.
    - **Regex Engine**: DFA-based pattern matching (replaces huge Python middleware).
    - **JSON Parsing**: Using `orjson` (Rust) for global serialization.

### 3. ⚖️ Automated Compliance (Legal Tech)
- **EU AI Act**: Generates audit-ready PDF certificates proving Data Residency.
- **US NIST AI RMF**: Generates "Safety Veto" reports and "Bias Audit" evidence.
- **CCPA/GDPR**: Built-in "Right to Erasure" and "Do Not Sell" endpoints.

### 4. 💸 Scientific Arbitrage
- **Market Oracle**: Syncs pricing from OpenRouter/Frankfurter public APIs.
- **Kalman Filter**: A State Space Model predicts which provider is stable/cheap in real-time. It doesn't just look at price; it looks at *volatility*.

---

## 🛠️ Architecture

```mermaid
graph TD
    User[Clients] -->|HTTPS| CF[Cloudflare Zero Trust]
    CF -->|HTTP/2 Granian| App[AgentShield Core]
    
    subgraph "Sovereign Container"
        App -->|Scrub PII| ONNX[Local PII Model]
        App -->|Sign Content| Rust[Rust Module]
        App -->|Log (Audit)| DB[(Supabase)]
        App -->|Cache (Speed)| Redis[(Redis + Lua)]
    end
    
    App -->|Safe Request| LLM[OpenAI / Groq / Anthropic]
```

## 🏁 Quick Start

### Prerequisites
- Docker & Docker Compose
- Environment variables (see `setup_guide.md`)

### Run Production
```bash
# 1. Build the Hybrid Image (Compiles Rust + Python)
docker build -t agentshield-core .

# 2. Run with Granian (Rust Server)
docker run -p 8080:8080 --env-file .env agentshield-core
```

## 📜 License
Proprietary. Built for the Sovereign AI Era.
