from fastapi import FastAPI
from app.routers import authorize, receipt, dashboard, proxy, onboarding
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.limiter import limiter

app = FastAPI(title="AgentShield API", version="1.0.0")

# Rate Limiter setup
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

import os

# 1. Configuración CORS (Production Ready)
# Leemos de variable de entorno. Ejemplo: "https://app.agentshield.io,https://admin.agentshield.io"
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

# Si estamos en modo, podemos permitir localhost por defecto si no se especificó nada
if not origins:
    # Default restrictivo o log de advertencia
    print("WARNING: No ALLOWED_ORIGINS set. CORS policy is empty effectively.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],    # Permitir GET, POST, PUT, OPTIONS
    allow_headers=["*"],    # Permitir headers como X-API-Key
)

# 1.5. Security Headers (Trusted Host)
# En producción, esto evita ataques de Host Header Injection
app.add_middleware(
    TrustedHostMiddleware, 
    allowed_hosts=["agentshield.onrender.com", "localhost", "127.0.0.1", "*.agentshield.io"]
)

# 2. Conectar Routers
app.include_router(authorize.router)
app.include_router(receipt.router)
app.include_router(dashboard.router)
app.include_router(proxy.router)
app.include_router(onboarding.router)

# Endpoint de salud para Render (ping)
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "agentshield-core"}