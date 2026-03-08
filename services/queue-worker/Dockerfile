FROM python:3.12-slim

WORKDIR /app

COPY services/shared ./services/shared
COPY services/queue-worker ./services/queue-worker

RUN pip install --no-cache-dir sqlalchemy psycopg2-binary requests redis

WORKDIR /app/services/queue-worker

CMD ["python", "worker.py"]
