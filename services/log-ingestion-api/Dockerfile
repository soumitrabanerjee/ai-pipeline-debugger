FROM python:3.12-slim

WORKDIR /app

COPY services/shared ./services/shared
COPY services/log-ingestion-api ./services/log-ingestion-api

RUN pip install --no-cache-dir fastapi uvicorn sqlalchemy psycopg2-binary requests redis

WORKDIR /app/services/log-ingestion-api

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
