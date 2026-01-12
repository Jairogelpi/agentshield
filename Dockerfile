# agentshield_core/Dockerfile

# ETAPA 1: Builder (Compilación rápida)
FROM python:3.13-slim AS builder

# 1. Instalar Rust y herramientas de compilación
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# 2. Instalar UV y Maturin
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
RUN uv pip install --system maturin

WORKDIR /app

# 3. Compilar el Módulo Rust
COPY rust_module /app/rust_module
WORKDIR /app/rust_module
ENV PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
RUN maturin build --release --strip

# 4. Instalar Dependencias Python + Nuestro Módulo Rust
WORKDIR /app
COPY requirements.txt .
RUN uv pip install --system --compile-bytecode \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt \
    rust_module/target/wheels/*.whl

# --- CAMBIO CRÍTICO AQUÍ ---
# 5. Descarga de modelos (FlashRank / ONNX)
# Eliminamos sentence-transformers y usamos flashrank para descargar el modelo "Nano"
# Esto evita descargas en tiempo de ejecución.
RUN mkdir -p /app/model_cache && \
    python -c "from flashrank import Ranker; Ranker(model_name='ms-marco-MiniLM-L-12-v2', cache_dir='/app/model_cache')"

# ETAPA 2: Runner (Imagen final ligera)
FROM python:3.13-slim

# Variables de optimización
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    # HF_HOME define donde busca FlashRank por defecto si no se le pasa cache_dir,
    # pero aquí lo estamos moviendo a /opt/models y el código usa cache_dir=/opt/models explícitamente.
    HF_HOME=/opt/models \
    TRANSFORMERS_OFFLINE=1 

WORKDIR /app

# Copiamos las librerías instaladas
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# --- CAMBIO CRÍTICO AQUÍ ---
# Copiamos el modelo descargado a /opt/models (Debe coincidir con tu reranker.py)
COPY --from=builder /app/model_cache /opt/models

# Copiamos el código fuente
COPY ./app /app/app

# Usuario no-root y permisos para la carpeta de modelos
RUN useradd -m appuser && \
    chown -R appuser /app && \
    chown -R appuser /opt/models

USER appuser

# Comando de arranque
CMD ["sh", "-c", "granian --interface asgi app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers ${WEB_CONCURRENCY:-1}"]