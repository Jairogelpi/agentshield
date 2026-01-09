from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import ORJSONResponse
from app.routers import authorize, receipt, dashboard, proxy, onboarding, compliance, analytics
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.limiter import limiter
from app.services.cache import init_semantic_cache_index
from app.services.market_oracle import update_market_rules

import os
import logging
from logging.handlers import QueueHandler, QueueListener
import queue
import atexit
import asyncio
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from logtail import LogtailHandler
from app.services.safe_logger import PIIRedactionFilter # PII Firewall
import sentry_sdk

# 0. Sentry Error Tracking
sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=1.0)

# 1. Configuración de Logs (Betterstack)
# Solo si existe el token, para no romper en dev local sin token
logtail_token = os.getenv("LOGTAIL_TOKEN")
if logtail_token:
    handler = LogtailHandler(source_token=logtail_token)
    
    # --- PII FIREWALL PARA LOGS ---
    # Cualquier log que salga hacia Betterstack será escaneado y limpiado anónimamente.
    pii_filter = PIIRedactionFilter()
    handler.addFilter(pii_filter)
    # ------------------------------
    
    # --- NON-BLOCKING LOGGING (Queue Pattern) ---
    # Logtail/Console I/O can be slow. We offload it to a background thread.
    log_queue = queue.Queue(-1) # Infinite queue
    queue_handler = QueueHandler(log_queue)
    
    # The listener runs in a separate thread and calls the actual expensive handlers
    listener = QueueListener(log_queue, handler)
    listener.start()
    atexit.register(listener.stop)
    
    # Configurar el logger ROOT de 'agentshield' para usar la cola
    logger = logging.getLogger("agentshield")
    logger.addHandler(queue_handler)
    logger.setLevel(logging.INFO)
    
    # También mantenemos el logger local de main
    main_logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)



def setup_observability(app):
    try:
        # Usamos nombres standard de OTEL para Grafana
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        headers_str = os.getenv("OTEL_EXPORTER_OTLP_HEADERS")
        
        if endpoint:
            # Parsear headers de "Key=Value,Key2=Value2" a dict
            headers = dict(h.split('=') for h in headers_str.split(',')) if headers_str else {}
            
            # Nombre de servicio
            service_name = os.getenv("OTEL_SERVICE_NAME", "AgentShield-Core")
            resource = Resource.create({"service.name": service_name})
            
            provider = TracerProvider(resource=resource)
            
            # Pasar los headers de Grafana directamente
            exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
            processor = BatchSpanProcessor(exporter)
            
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
            
            # Instrumentar FastAPI automáticamente
            FastAPIInstrumentor.instrument_app(app)
            logger.info(f"✅ Observability initialized for {service_name} -> Grafana Cloud")
            
    except Exception as e:
        logger.error(f"Grafana/OTEL Init Error: {e}")

from contextlib import asynccontextmanager
from app.db import recover_pending_charges

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    logger.info("🚀 AgentShield Core Starting...")
    
    # 1. Recuperación de Cobros (WAL Recovery)
    try:
        asyncio.create_task(recover_pending_charges())
    except Exception as e:
        logger.critical(f"Failed to start Recovery Worker: {e}")
        
        
    # 2. Inicializar Cache Vectorial
    await init_semantic_cache_index()

    # 3. Iniciar Oráculo de Mercado (Async) - Obtiene precios "frescos"
    asyncio.create_task(update_market_rules())

    yield 
    
    # --- SHUTDOWN ---
    logger.info("🛑 AgentShield Core Shutting Down...")

app = FastAPI(
    title="AgentShield API", 
    version="1.0.0", 
    lifespan=lifespan,
    default_response_class=ORJSONResponse
)

# Setup Observability (OTEL + Grafana)
setup_observability(app)

# --- 🛡️ SECURITY MIDDLEWARE: CLOUDFLARE AUTH + HSTS 🛡️ ---
@app.middleware("http")
async def security_guard(request: Request, call_next):
    # 1. Bypass para Health Check y Desarrollo
    if request.url.path == "/health" or os.getenv("ENVIRONMENT") == "development":
        return await call_next(request)

    # 2. VERIFICACIÓN DE CLOUDFLARE (El Candado)
    # Usamos la nueva llave 'X-AgentShield-Auth'
    expected_secret = os.getenv("CLOUDFLARE_PROXY_SECRET")
    incoming_secret = request.headers.get("X-AgentShield-Auth")

    if expected_secret and incoming_secret != expected_secret:
        # Usamos el logger 'agentshield' configurado globalmente
        # Intentamos sacar la IP real para el log, si no, usamos la del host
        real_ip = request.headers.get("cf-connecting-ip", request.client.host)
        logger.warning(f"⛔ Direct access blocked from {real_ip}")
        return JSONResponse(
            status_code=403, 
            content={"error": "Direct access forbidden. Use getagentshield.com"}
        )

    # 3. PROCESAR PETICIÓN
    response = await call_next(request)

    # 4. INYECCIÓN HSTS (El Blindaje SSL)
    # Obliga al navegador a recordar que este sitio SOLO funciona con HTTPS por 1 año.
    # includeSubDomains: Protege también api.tudominio.com, etc.
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    # 5. CABECERAS EXTRA DE SEGURIDAD (Bonus Enterprise)
    # Evita que tu API sea cargada en iframes ajenos (Clickjacking)
    response.headers["X-Frame-Options"] = "DENY"
    # Evita que el navegador adivine tipos de archivo (MIME Sniffing)
    response.headers["X-Content-Type-Options"] = "nosniff"

    return response

# 1. Configuración CORS (Production Ready)
# Leemos de variable de entorno. Ejemplo: "https://app.agentshield.io,https://admin.agentshield.io"
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

# Si estamos en modo, podemos permitir localhost por defecto si no se especificó nada
if not origins:
    # Default restrictivo o log de advertencia
    logger.warning("WARNING: No ALLOWED_ORIGINS set. CORS policy is empty effectively.")

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
    allowed_hosts=[
        "getagentshield.com",       # ✅ Tu dominio real
        "www.getagentshield.com",   # ✅ Tu subdominio
        "localhost",                # ✅ Desarrollo
        "127.0.0.1"                 # ✅ Desarrollo
    ]
    # Eliminamos "agentshield.onrender.com" para forzar que entren por Cloudflare
)

# 1.8. Compression (Performance)
# ELIMINADO: Cloudflare gestiona Gzip/Brotli en el Edge.
# Hacerlo en Python es gastar CPU innecesariamente.
# app.add_middleware(GZipMiddleware, minimum_size=500)

# 2. Conectar Routers
app.include_router(authorize.router)
app.include_router(receipt.router)
app.include_router(dashboard.router)
app.include_router(proxy.router)
app.include_router(onboarding.router)
app.include_router(compliance.router)
app.include_router(analytics.router)

# Endpoint de salud para Render (ping)
# Endpoint de salud para Render (Deep Health Check)
from app.db import redis_client, supabase
import time

@app.get("/health")
async def health_check(full: bool = False):
    """
    Ping de salud. Si full=True, verifica DB y Redis.
    Render llama a esto a menudo, así que por defecto es rápido.
    """
    health_status = {"status": "ok", "service": "agentshield-core", "timestamp": time.time()}
    
    if full:
        try:
            # 1. Check Redis
            if not await redis_client.ping():
                raise Exception("Redis PING failed")
            health_status["redis"] = "connected"
            
            # 2. Check Supabase (Query simple)
            supabase.table("cost_centers").select("id").limit(1).execute()
            health_status["db"] = "connected"
            
        except Exception as e:
            # Si infraestructura crítica falla, 503
            logger.critical(f"Health Check Failed: {e}")
            raise HTTPException(status_code=503, detail=f"Infrastructure Error: {e}")
            
    return health_status

