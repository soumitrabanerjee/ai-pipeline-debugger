FROM python:3.12-slim

WORKDIR /app

COPY services/ai-debugging-engine ./services/ai-debugging-engine

RUN pip install --no-cache-dir fastapi uvicorn requests

WORKDIR /app/services/ai-debugging-engine

EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
