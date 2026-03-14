FROM python:3.12-slim

WORKDIR /app

COPY services/shared ./services/shared
COPY services/alerting ./services/alerting
COPY services/log-processing-layer ./services/log-processing-layer
COPY services/root-cause-engine ./services/root-cause-engine
COPY services/queue-worker ./services/queue-worker

RUN pip install --no-cache-dir \
    sqlalchemy \
    psycopg2-binary \
    requests \
    redis \
    pgvector

WORKDIR /app/services/queue-worker

ENV PYTHONUNBUFFERED=1
CMD ["python", "worker.py"]
