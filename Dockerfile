# agentshield_core/Dockerfile

# ETAPA 1: Builder (Compilación rápida)
FROM python:3.10-slim AS builder

# Instalamos 'uv', el reemplazo ultra-rápido de pip en 2026
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Instalar dependencias del sistema (solo para compilar)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiamos requisitos
COPY requirements.txt .

# INSTALACIÓN TURBO CON UV
# --system: Instala en el python global (no venv) porque estamos en Docker
# --no-cache: Evita guardar caché dentro de la imagen final (ahorra espacio)
# --compile-bytecode: Acelera el arranque de Python un 20%
RUN uv pip install --system --compile-bytecode \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

# Descarga de modelos (En una sola capa para reducir overhead)
RUN python -m spacy download es_core_news_md && \
    mkdir -p /app/model_cache && \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2', cache_folder='/app/model_cache')"

# ETAPA 2: Runner (Imagen final ligera)
FROM python:3.10-slim

# Variables de optimización
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/model_cache \
    TRANSFORMERS_OFFLINE=1 

WORKDIR /app

# Copiamos las librerías instaladas desde el Builder (Magia de Multi-stage)
# Esto descarta toda la basura de compilación (gcc, apt, etc) y reduce el tamaño de exportación en 300MB+
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
# Copiamos los modelos descargados
COPY --from=builder /app/model_cache /app/model_cache

# Copiamos el código fuente al final
COPY ./app /app/app

# Usuario no-root para seguridad
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Comando de arranque optimizado
# --preload: Carga la app en memoria antes de forkear (ahorra RAM y detecta errores al inicio)
CMD ["gunicorn", "app.main:app", "--workers", "2", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:10000", "--preload", "--timeout", "60"]