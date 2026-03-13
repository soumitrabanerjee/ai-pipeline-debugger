FROM python:3.12-slim
WORKDIR /app
COPY services/log-collection-layer ./services/log-collection-layer
COPY services/spark-jobs ./services/spark-jobs
RUN pip install --no-cache-dir fastapi uvicorn requests
WORKDIR /app/services/log-collection-layer
CMD ["uvicorn", "webhook_collector:app", "--host", "0.0.0.0", "--port", "8003"]
