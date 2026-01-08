# Usamos slim para base ligera
FROM python:3.10-slim

# Evita que Python escriba archivos .pyc y fuerza logs en tiempo real
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/code/model_cache

WORKDIR /code

# Instalar dependencias del sistema necesarias para compilar algunas libs de Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 1. Copiamos SOLO requirements primero (Caché de Docker)
# Si no cambias requirements.txt, Docker saltará este paso instantáneamente
COPY ./requirements.txt /code/requirements.txt

# 2. Instalación optimizada sin caché de pip (reduce tamaño imagen final)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /code/requirements.txt

# 3. Descarga de Modelos (Solo si cambian)
# Spacy
RUN python -m spacy download es_core_news_md
# Sentence Transformers (Embeddings)
RUN mkdir -p /code/model_cache && \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2', cache_folder='/code/model_cache')"

# 4. Copiamos el código AL FINAL
# Así, si cambias una línea en main.py, el deploy tarda segundos, no minutos
COPY ./app /code/app

# Ajuste de Gunicorn: Aumentamos timeout por si la carga de modelos es lenta
# Bind to 0.0.0.0:10000 to satisfy Render port detection
CMD ["gunicorn", "app.main:app", "--workers", "2", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:10000", "--preload", "--timeout", "120"]