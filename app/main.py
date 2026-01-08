from fastapi import FastAPI
from app.routers import authorize, receipt, dashboard, proxy, onboarding, compliance, analytics
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.limiter import limiter

from slowapi.errors import RateLimitExceeded
from app.limiter import limiter
from app.services.cache import init_semantic_cache_index

import os
import logging
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
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
    
    logger = logging.getLogger(__name__)
    logger.addHandler(handler)
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
            print(f"✅ Observability initialized for {service_name} -> Grafana Cloud")
            
    except Exception as e:
        print(f"Grafana/OTEL Init Error: {e}")

app = FastAPI(title="AgentShield API", version="1.0.0")

# Setup Observability (OTEL + Grafana)
setup_observability(app)

# Inicializar Cache Vectorial
init_semantic_cache_index()

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
app.include_router(compliance.router)
app.include_router(analytics.router)

# Endpoint de salud para Render (ping)
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "agentshield-core"}

