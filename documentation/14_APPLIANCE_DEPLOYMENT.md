# AgentShield Deployment Guide: Hybrid Cloud & Sovereign

This guide describes how to deploy AgentShield in two modes: **SaaS** (Managed Cloud) and **Sovereign** (On-Premise/Appliance).

## Hybrid Sales Strategy
AgentShield supports a dual-tier deployment model leveraging the same codebase:

1.  **AgentShield Cloud (SaaS)**:
    *   **Infrastructure**: Hosted on Render/Vercel (Managed by You).
    *   **Tenancy**: Multi-Tenant (Standard) or Dedicated Instance (Enterprise).
    *   **Ideal For**: Startups, Agencies, Mid-Market.
    *   **Pricing**: Monthly Subscription + Usage.

2.  **AgentShield Sovereign (On-Premise)**:
    *   **Infrastructure**: Docker binary installed on Client's Server.
    *   **Tenancy**: Single-Tenant (Physically Isolated).
    *   **Ideal For**: Banks, Government, Health.
    *   **Pricing**: Annual License ($50k+) + Support.

## Technical Requirements (Critical)
To run the full **FileGuardian** with OCR (Tesseract) and Local AI (DeBERTa), you must size the infrastructure correctly.

### Minimum Specs (Render/Docker)
| Component | Minimum RAM | CPU | Notes |
|-----------|-------------|-----|-------|
| Core API  | **2 GB**    | 1 vCPU | Required for Tesseract + ONNX Runtime overhead. |
| Redis     | 256 MB      | Shared | For caching and rate limiting. |
| Postgres  | 512 MB      | Shared | With pgvector plugin. |

> [!WARNING]
> Do NOT deploy on Render "Free" or "Starter" (512MB) plans. The OCR engine will cause OOM (Out Of Memory) crashes during file uploads. Use "Standard" (2GB+) instances.

## Dedicated SaaS Configuration (Private Cloud)
To offer a "Private Cloud" experience without on-premise friction:
1.  Deploy a new backend instance on Render (e.g., `api-bank-vip.onrender.com`).
2.  Update the **Master Database**:
    ```sql
    UPDATE tenants SET backend_api_url = 'https://api-bank-vip.onrender.com/v1' WHERE slug = 'banco-vip';
    ```
3.  The shared frontend (`app.agentshield.ai`) will automatically route traffic to the private instance.

## Deployment Steps (Docker Compose)
For Sovereign/On-Premise deployments:

1.  **Configure Environment**:
    Ensure OpenAI/Provider keys and Supabase URL/Key are set in `.env`.

2.  **Deploy**:
    ```bash
    docker-compose up -d --build
    ```

3.  **Access**:
    - **Web Interface**: `http://localhost:3000`
    - **API Docs**: `http://localhost:8000/docs`
