import sys
import os
import redis as redis_lib
from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Add project root to Python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(PROJECT_ROOT)

from services.shared.models import Base, Pipeline, PipelineRun

app = FastAPI(title="Log Ingestion API", version="0.2.0")

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://debugger:debugger@localhost:5433/pipeline_debugger"
)
print(f"Connecting to database at: {DATABASE_URL}")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
STREAM_NAME = "log_events"
redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)


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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest", status_code=202)
def ingest(event: LogEvent, db: Session = Depends(get_db)):
    # 1. Update pipeline status immediately (fast DB write)
    pipeline = db.query(Pipeline).filter(Pipeline.name == event.job_id).first()
    status = "Failed" if event.level == "ERROR" else "Success"

    if pipeline:
        pipeline.status = status
        pipeline.last_run = "Just now"
    else:
        pipeline = Pipeline(name=event.job_id, status=status, last_run="Just now")
        db.add(pipeline)

    # 2. Record this individual run
    existing_run = db.query(PipelineRun).filter(PipelineRun.run_id == event.run_id).first()
    if not existing_run:
        db.add(PipelineRun(
            pipeline_name=event.job_id,
            run_id=event.run_id,
            status=status,
            created_at=event.timestamp,
        ))

    db.commit()

    # 3. For errors, publish to queue — AI analysis happens async in the worker
    if event.level == "ERROR":
        redis_client.xadd(STREAM_NAME, {
            "job_id": event.job_id,
            "run_id": event.run_id,
            "message": event.message,
        })

    return {"status": "accepted", "run_id": event.run_id}
