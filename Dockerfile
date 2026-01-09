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
# Copiamos solo lo necesario para cachear la compilación de crates
COPY rust_module /app/rust_module
WORKDIR /app/rust_module
# Esto compila el código Rust y genera un archivo .whl (wheel) de Python optimizado
RUN maturin build --release --strip

# 4. Instalar Dependencias Python + Nuestro Módulo Rust
WORKDIR /app
COPY requirements.txt .
# Instalamos requirements Y el wheel que acabamos de cocinar
RUN uv pip install --system --compile-bytecode \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt \
    target/wheels/*.whl

# Descarga de modelos (Solo Embeddings ya que PII ahora es API/Rust)
RUN mkdir -p /app/model_cache && \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2', cache_folder='/app/model_cache')" && \
    mkdir -p /app/models
    # NOTA: En producción, descargar aquí el modelo ONNX:
    # RUN wget https://huggingface.co/.../pii-ner-quantized.onnx -O /app/models/pii-ner-quantized.onnx
    # RUN wget https://huggingface.co/.../tokenizer.json -O /app/models/tokenizer.json

# ETAPA 2: Runner (Imagen final ligera)
FROM python:3.13-slim

# Variables de optimización
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    HF_HOME=/app/model_cache \
    TRANSFORMERS_OFFLINE=1 

WORKDIR /app

# Copiamos las librerías instaladas desde el Builder (Magia de Multi-stage)
# Esto descarta toda la basura de compilación (gcc, apt, etc) y reduce el tamaño de exportación en 300MB+
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
# Copiamos los modelos descargados
COPY --from=builder /app/model_cache /app/model_cache

# Copiamos el código fuente al final
COPY ./app /app/app

# Usuario no-root para seguridad
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Comando de arranque optimizado (Granian - Rust HTTP Server)
CMD ["granian", "--interface", "asgi", "app.main:app", "--host", "0.0.0.0", "--port", "10000", "--workers", "2", "--threading-mode", "runtime"]