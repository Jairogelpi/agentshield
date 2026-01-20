# 00. AgentShield Strategic Technical Manifest (2026)

> **Document Purpose:** This manifest maps the high-level strategic claims of AgentShield directly to the underlying technical implementation. It serves as a proof-of-work for investors, auditors, and technical evaluators.

---

## 1. Thesis: Execution vs. Bureaucracy (The Anti-OneTrust)

**The Promise:** while OneTrust relies on manual forms and passive pdf reports, AgentShield enforces compliance in the millisecond the data attempts to move.

### Technical Proof
*   **Rust-Powered Scrubbing (<1ms):**
    *   **Implementation:** `rust_module/src/lib.rs`
    *   **Mechanism:** Uses `regex::Regex` compiled in Rust for zero-copy PII detection (`scrub_pii_fast`).
    *   **Integration:** `app/services/pii_guard.py` calls this native module on the hot path.
*   **DPO-as-Code:**
    *   **Implementation:** `scripts/schema_compliance.sql` & `app/services/compliance.py`
    *   **Mechanism:** Automated SQL schemas for audit logs (`compliance_actions`) and immutable certificates. Compliance is not a process; it is a database constraint.

---

## 2. Thesis: Profit Center vs. Cost Center (The Anti-Credo)

**The Promise:** Credo AI is an insurance premium. AgentShield is an arbitrage machine that pays for itself.

### Technical Proof
*   **Real-Time Financial Arbitrage:**
    *   **Implementation:** `app/services/arbitrage.py`
    *   **Mechanism:**
        *   **Complexity Analysis:** An "AI Judge" (`analyze_complexity`) scores prompts (0-100).
        *   **Reinforcement Learning:** Uses Q-Learning stored in Redis (`rl:q:{state}`) to learn which models offer the best ROI.
        *   **Model Swapping:** Automatically downgrades simple tasks from expensive models (GPT-4) to cheaper ones (Llama-3/Haiku), capturing the spread.
*   **Invisible Savings:**
    *   **Implementation:** `app/services/arbitrage.py` (Line 251)
    *   **Mechanism:** The system explicitly calculates and logs the delta between the requested model price and the actual execution price.

---

## 3. Thesis: Sovereignty vs. Dependence (The Anti-Lakera)

**The Promise:** Lakera requires shipping data to their API or running heavyweight containers. AgentShield runs locally on commodity hardware (2GB RAM).

### Technical Proof
*   **Local-First Architecture:**
    *   **Implementation:** `app/services/pii_guard.py`
    *   **Mechanism:** Default behavior is local Rust execution. Cloud fallback (`FORCE_CLOUD_FALLBACK`) is optional and lazy. Data never leaves the perimeter unless explicitly configured.
*   **AgentShield OS:**
    *   **Implementation:** `Dockerfile` & `app/main.py`
    *   **Mechanism:** A single lightweight container bundles the Proxy, the Financial Engine, and the Vector Store. It is not just a firewall; it is a complete operating micro-kernel for AI.

---

## 4. The "Secret Weapons" (Unmatched Features)

These are features that no competitor currently offers in a unified package.

### A. Knowledge Royalties (Internal Marketplace)
*   **Concept:** Turns data silos into a marketplace where departments pay each other for knowledge.
*   **Implementation:** `app/services/marketplace.py`
*   **Mechanism:** Implements `enforce_data_license` to check if a consumer has paid for the "listing". Supports `SUMMARY_ONLY` licenses to monetize data without revealing raw text.

### B. Forensic Time-Travel
*   **Concept:** Mathematical proof of what the system rules were at any past moment.
*   **Implementation:** `app/services/snapshotter.py`
*   **Mechanism:** Generates a SHA-256 hash of the entire configuration state (policies + budgets + system config) at the moment of execution. This allows for cryptographic replay of liability.

### C. Green AI & Carbon Routing
*   **Concept:** ESG compliance as a native routing feature.
*   **Implementation:** `app/services/carbon.py`
*   **Mechanism:** Connects to `CarbonOracle` for real-time grid intensity. Forces routing to `agentshield-eco` models when carbon budgets or grid intensity limits are exceeded.

### D. Zero-Trust Entropy (Unknown Secret Detection)
*   **Concept:** PII protection that blocks what it doesn't know.
*   **Implementation:** `app/services/pii_guard.py` (Entropy Engine)
*   **Mechanism:** Uses Shannon Entropy analysis to mathematically detect high-randomness strings (like API keys or passwords) that evade standard Regex patterns.

### E. Custom Policy Copilot (Natural Language Rules)
*   **Concept:** "Policy-as-Code" for non-technical users.
*   **Implementation:** `app/services/policy_copilot.py` & `custom_pii_rules` Table.
*   **Mechanism:** Uses an AI agent to translate natural language ("Block project codes like PRJ-1234") into high-performance Regex, which is then hot-loaded by the PII Guard.

---

## 5. Thesis: Appliance vs. API (The Anti-SaaS)

**The Promise:** Don't sell an API integration. Sell a "ChatGPT Enterprise" box that plugs into the wall.

### Technical Proof
*   **The AgentShield Appliance:**
    *   **Implementation:** `docker-compose.yml`
    *   **Mechanism:** Bundles **OpenWebUI** (Frontend) directly with **AgentShield Core** (Backend). The customer deploys one container set. To the employee, it looks like ChatGPT. To the CISO, it looks like a Vault.
*   **Explicit Flight Modes:**
    *   **Implementation:** `app/routers/proxy.py`
    *   **Mechanism:**
        *   `agentshield-fast`: Aggressive Financial Arbitrage (High Savings).
        *   `agentshield-smart`: Zero-Risk direct routing to GPT-4o ("Panic Button" for executives).

---

## Conclusion
AgentShield is not "Governanceware". It is a **Sovereign AI Operating System**. The code exists, runs effectively, and solves the three core problems of the Enterprise AI era: **Control, Cost, and Conscience.**
