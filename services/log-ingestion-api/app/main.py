import sys
import os
import uuid
import hashlib
import redis as redis_lib
from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime, timezone
from typing import Optional

# Add project root to Python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(PROJECT_ROOT)

from services.shared.models import Base, Pipeline, PipelineRun, ApiKey
from services.shared.scrubber import scrub_text

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


def _get_workspace_from_api_key(
    x_api_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> str:
    """
    Required x-api-key header validation.

    - Absent header: raises 401.
    - Present but invalid/revoked: raises 401.
    - Valid: returns the workspace_id bound to that key.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required. Include x-api-key header.")
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    record = db.query(ApiKey).filter(
        ApiKey.key_hash == key_hash,
        ApiKey.is_active == True,
    ).first()
    if not record:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    return record.workspace_id


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ── Core ingest logic (no FastAPI Depends — safe to call from webhook handlers) ─

def _do_ingest(event: LogEvent, workspace_id: str, db: Session) -> dict:
    """
    Persist pipeline + run metadata and publish to Redis.
    workspace_id is passed explicitly so callers control which tenant is written to.
    """
    run_status = "Failed" if event.level == "ERROR" else "Success"

    # 1. Upsert pipeline row scoped to this workspace
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pipeline = db.query(Pipeline).filter(
        Pipeline.workspace_id == workspace_id,
        Pipeline.name         == event.job_id,
    ).first()
    if pipeline:
        pipeline.last_run = now
    else:
        pipeline = Pipeline(
            workspace_id = workspace_id,
            name         = event.job_id,
            status       = run_status,
            last_run     = now,
        )
        db.add(pipeline)

    # 2. Record this individual run (skip if run_id already exists)
    if not db.query(PipelineRun).filter(PipelineRun.run_id == event.run_id).first():
        db.add(PipelineRun(
            workspace_id  = workspace_id,
            pipeline_name = event.job_id,
            run_id        = event.run_id,
            status        = run_status,
            created_at    = event.timestamp,
        ))

    db.flush()  # write PipelineRun so the query below sees it

    # 3. Derive pipeline status from the MOST RECENT run for this workspace.
    #    Prevents a delayed old-error event from flipping a recovered pipeline back to Failed.
    latest_run = (
        db.query(PipelineRun)
        .filter(
            PipelineRun.workspace_id  == workspace_id,
            PipelineRun.pipeline_name == event.job_id,
        )
        .order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc())
        .first()
    )
    pipeline.status = latest_run.status if latest_run else run_status

    db.commit()

    # 4. For errors, scrub PII/secrets then publish to queue
    if event.level == "ERROR":
        redis_client.xadd(STREAM_NAME, {
            "workspace_id": workspace_id,
            "job_id":       event.job_id,
            "run_id":       event.run_id,
            "message":      scrub_text(event.message),
        })

    return {"status": "accepted", "run_id": event.run_id}


# ── Route handlers ─────────────────────────────────────────────────────────────

@app.post("/ingest", status_code=202)
def ingest(
    event: LogEvent,
    db: Session = Depends(get_db),
    api_key_workspace: str = Depends(_get_workspace_from_api_key),
):
    # API key workspace always overrides the payload field
    return _do_ingest(event, api_key_workspace, db)


class GenericWebhookEvent(BaseModel):
    pipeline: str
    level: str          # "ERROR" | "INFO" | etc.
    message: str
    timestamp: str | None = None   # ISO-8601; defaults to now if omitted


@app.post("/webhook/generic", status_code=202)
def webhook_generic(
    event: GenericWebhookEvent,
    db: Session = Depends(get_db),
    api_key_workspace: str = Depends(_get_workspace_from_api_key),
):
    """Simplified webhook — accepts {pipeline, level, message, timestamp}."""
    ts     = event.timestamp or datetime.now(timezone.utc).isoformat()
    run_id = f"{event.pipeline}-{uuid.uuid4().hex[:8]}"
    synthetic = LogEvent(
        source       = "webhook",
        workspace_id = api_key_workspace,
        job_id       = event.pipeline,
        run_id       = run_id,
        level        = event.level.upper(),
        timestamp    = ts,
        message      = event.message,
    )
    return _do_ingest(synthetic, api_key_workspace, db)


class AirflowWebhookEvent(BaseModel):
    """
    Matches the payload shape sent by Airflow's on_failure_callback / on_success_callback.
    All fields that Airflow typically includes; extras are ignored.
    """
    dag_id:          str
    run_id:          str
    task_id:         str | None = None
    state:           str                   # 'failed' | 'success' | 'upstream_failed' etc.
    execution_date:  str | None = None     # ISO-8601
    log_url:         str | None = None
    exception:       str | None = None     # exception message when state=failed
    try_number:      int | None = None


@app.post("/webhook/airflow", status_code=202)
def webhook_airflow(
    event: AirflowWebhookEvent,
    db: Session = Depends(get_db),
    api_key_workspace: str = Depends(_get_workspace_from_api_key),
):
    """
    Airflow on_failure_callback / on_success_callback webhook.

    Map Airflow fields → internal LogEvent:
      dag_id        → job_id (pipeline name)
      run_id        → run_id
      state=failed  → level ERROR
      state=success → level INFO
      exception     → message (falls back to a generic message)
      execution_date→ timestamp
    """
    failed_states = {"failed", "upstream_failed", "up_for_retry"}
    level   = "ERROR" if event.state.lower() in failed_states else "INFO"
    ts      = event.execution_date or datetime.now(timezone.utc).isoformat()
    message = event.exception or f"DAG {event.dag_id} — task {event.task_id or 'N/A'} {event.state}"

    synthetic = LogEvent(
        source       = "airflow",
        workspace_id = api_key_workspace,
        job_id       = event.dag_id,
        run_id       = event.run_id,
        task_id      = event.task_id,
        level        = level,
        timestamp    = ts,
        message      = message,
        raw_log_uri  = event.log_url,
    )
    return _do_ingest(synthetic, api_key_workspace, db)
