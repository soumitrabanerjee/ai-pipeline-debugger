"""
Webhook Collector — FastAPI service that accepts push notifications from
pipeline orchestrators (Airflow, Databricks, Prefect, etc.) and forwards
them to the ingestion API.

Supported webhook formats:

  1. Airflow on_failure_callback
     POST /webhook/airflow
     { "dag_id": "customer_etl", "run_id": "run_2026...", "task_id": "...",
       "exception": "ExecutorLostFailure: ...", "log_url": "http://..." }

  2. Generic / custom
     POST /webhook/generic
     { "pipeline": "my-pipeline", "run_id": "...", "level": "ERROR",
       "message": "Something went wrong", "timestamp": "2026-..." }

Both endpoints return 202 Accepted immediately.

Usage:
  uvicorn webhook_collector:app --host 0.0.0.0 --port 8003

Environment variables:
  INGEST_URL   — ingestion API (default: http://localhost:8000/ingest)
"""

import os
import uuid
import requests
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

INGEST_URL = os.getenv("INGEST_URL", "http://localhost:8000/ingest")

app = FastAPI(title="Log Collection Webhook Collector", version="1.0.0")


# ── schemas ───────────────────────────────────────────────────────────────────

class AirflowWebhook(BaseModel):
    dag_id: str
    run_id: str
    task_id: Optional[str] = None
    exception: str                  # Airflow passes the exception string here
    log_url: Optional[str] = None
    execution_date: Optional[str] = None


class GenericWebhook(BaseModel):
    pipeline: str
    run_id: Optional[str] = None
    level: str = "ERROR"
    message: str
    timestamp: Optional[str] = None
    source: Optional[str] = "webhook"


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _forward(payload: dict):
    """POST the normalised event to the ingestion API (fire-and-forget)."""
    try:
        resp = requests.post(INGEST_URL, json=payload, timeout=10)
        print(
            f"[webhook] Forwarded pipeline={payload['job_id']} "
            f"run={payload['run_id']} → HTTP {resp.status_code}"
        )
    except Exception as e:
        print(f"[webhook] Forward failed: {e}")


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook/airflow", status_code=202)
def airflow_webhook(body: AirflowWebhook, background: BackgroundTasks):
    """
    Accepts Airflow on_failure_callback payloads.

    Airflow config example:
      default_args = {
          "on_failure_callback": lambda ctx: requests.post(
              "http://collector:8003/webhook/airflow",
              json={
                  "dag_id": ctx["dag"].dag_id,
                  "run_id": ctx["run_id"],
                  "task_id": ctx["task_instance"].task_id,
                  "exception": str(ctx.get("exception", "Unknown error")),
              }
          )
      }
    """
    payload = {
        "source": "airflow",
        "workspace_id": "default",
        "job_id": body.dag_id,
        "run_id": body.run_id,
        "task_id": body.task_id,
        "level": "ERROR",
        "timestamp": body.execution_date or _now_iso(),
        "message": body.exception,
        "raw_log_uri": body.log_url,
    }
    background.add_task(_forward, payload)
    return {"status": "accepted", "run_id": body.run_id}


@app.post("/webhook/generic", status_code=202)
def generic_webhook(body: GenericWebhook, background: BackgroundTasks):
    """
    Generic webhook — works with any system that can HTTP POST.

    Example curl:
      curl -X POST http://localhost:8003/webhook/generic \\
           -H 'Content-Type: application/json' \\
           -d '{"pipeline":"my-etl","level":"ERROR","message":"OOM error"}'
    """
    run_id = body.run_id or str(uuid.uuid4())
    payload = {
        "source": body.source or "webhook",
        "workspace_id": "default",
        "job_id": body.pipeline,
        "run_id": run_id,
        "level": body.level.upper(),
        "timestamp": body.timestamp or _now_iso(),
        "message": body.message,
    }
    background.add_task(_forward, payload)
    return {"status": "accepted", "run_id": run_id}
