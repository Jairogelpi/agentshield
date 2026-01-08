# Dockerfile
FROM python:3.10-slim

WORKDIR /code

COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
RUN python -m spacy download es_core_news_md

# Asegurar que HuggingFace use una ruta predecible
ENV TRANSFORMERS_CACHE=/code/model_cache
RUN mkdir -p /code/model_cache

# Pre-descarga el modelo en la ruta específica
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2', cache_folder='/code/model_cache')"

COPY ./app /code/app

# Comando para correr Gunicorn (Production Optimized)
# --preload: Carga la app en el master antes de forkear (Ahorra RAM compartida)
CMD ["gunicorn", "app.main:app", "--workers", "2", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:80", "--preload", "--timeout", "120"]