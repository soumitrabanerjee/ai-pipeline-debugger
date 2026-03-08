FROM python:3.12-slim

WORKDIR /app

COPY services/shared ./services/shared
COPY services/api-layer ./services/api-layer

RUN pip install --no-cache-dir fastapi uvicorn sqlalchemy psycopg2-binary

WORKDIR /app/services/api-layer

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
