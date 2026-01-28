import logging
import asyncio
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse

from app.config import settings
from app.middleware.auth import global_security_guard
from app.middleware.security import security_guard_middleware
from app.services.monitoring import setup_monitoring
from app.services.cache import init_semantic_cache_index
from app.services.market_oracle import update_market_rules
from app.db import recover_pending_charges, redis_client, supabase
from app.services.pricing_sync import sync_universal_prices

# Global state for Readiness Probe
MODELS_LOADED = False
logger = logging.getLogger("agentshield")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 AgentShield Core Starting...")
    
    # 1. Recovery & Initializations
    asyncio.create_task(recover_pending_charges())
    asyncio.create_task(init_semantic_cache_index())
    asyncio.create_task(update_market_rules())
    asyncio.create_task(sync_universal_prices())

    # 2. WARMUP (Models in Memory)
    async def warmup_models():
        logger.info("⏳ Warming up local AI models...")
        try:
            from app.services.pii_guard import redact_pii_sync
            from app.services.reranker import get_reranker_model
            await asyncio.to_thread(get_reranker_model)
            await asyncio.to_thread(redact_pii_sync, "Warmup")
            global MODELS_LOADED
            MODELS_LOADED = True
            logger.info("✅ System Fully Operational.")
        except Exception as e:
            logger.warning(f"⚠️ Warmup Partial Fail: {e}")

    asyncio.create_task(warmup_models())
    yield
    logger.info("🛑 AgentShield Core Shutting Down...")

app = FastAPI(
    title="AgentShield API",
    version="1.0.0",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
    dependencies=[Depends(global_security_guard)],
)

# Setup Monitoring & Middlewares
setup_monitoring(app)
app.middleware("http")(security_guard_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"],
)

# Register Routers
from app.routers import (
    admin_chat, admin_roles, analytics, audit, authorize, 
    compliance, dashboard, embeddings, feedback, forensics, 
    images, invoices, onboarding, proxy, public_config, 
    receipt, tools, trust, webhooks
)

app.include_router(public_config.router)
app.include_router(authorize.router)
app.include_router(receipt.router)
app.include_router(dashboard.router)
app.include_router(proxy.router)
app.include_router(onboarding.router)
app.include_router(compliance.router)
app.include_router(invoices.router)
app.include_router(analytics.router)
app.include_router(audit.router)
app.include_router(embeddings.router)
app.include_router(feedback.router)
app.include_router(admin_chat.router)
app.include_router(tools.router)
app.include_router(images.router)
app.include_router(forensics.router)
app.include_router(trust.router)
app.include_router(admin_roles.router)
app.include_router(webhooks.router)

@app.get("/health")
async def health_check(request: Request, full: bool = False):
    if not MODELS_LOADED:
        return JSONResponse(status_code=200, content={"status": "warming_up", "ready": False})

    health_status = {
        "status": "ok",
        "ready": True,
        "timestamp": time.time(),
    }

    if full:
        try:
            if not await redis_client.ping():
                raise Exception("Redis PING failed")
            supabase.table("cost_centers").select("id").limit(1).execute()
            health_status["infra"] = "connected"
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))

    return health_status
