from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Log Ingestion API", version="0.1.0")


class LogEvent(BaseModel):
    source: str
    workspace_id: str
    job_id: str
    run_id: str
    task_id: str | None = None
    level: str
    timestamp: str
    message: str
    raw_log_uri: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest")
def ingest(event: LogEvent) -> dict[str, str]:
    # TODO: publish to Kafka/Redis Streams
    return {"status": "accepted", "run_id": event.run_id}
