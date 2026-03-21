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
import subprocess
import sys
import requests
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, Header, HTTPException, Response
from pydantic import BaseModel

INGEST_URL   = os.getenv("INGEST_URL",   "http://localhost:8000/ingest")
SPARK_JOBS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "spark-jobs"
)

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


def _forward(payload: dict, api_key: str) -> requests.Response:
    """POST the normalised event to the ingestion API. Returns the response."""
    resp = requests.post(INGEST_URL, json=payload, headers={"x-api-key": api_key}, timeout=10)
    print(
        f"[webhook] Forwarded pipeline={payload['job_id']} "
        f"run={payload['run_id']} → HTTP {resp.status_code}"
    )
    return resp


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Spark job submission ───────────────────────────────────────────────────────

def _run_spark_job(script: str, job_id: str, run_id: str):
    """Run a PySpark script as a subprocess (fire-and-forget background task)."""
    script_path = os.path.join(SPARK_JOBS_DIR, script)
    env = os.environ.copy()
    env.update({
        "JOB_ID":      job_id,
        "WEBHOOK_URL": "http://localhost:8003/webhook/generic",
        "SPARK_LOG_DIR": "/tmp/spark-logs",
    })
    print(f"[spark-submit] Launching {script} (run_id={run_id})")
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        print(f"[spark-submit] {script} exited with code {result.returncode}")
        if result.stdout:
            print(result.stdout[-2000:])   # tail last 2 KB
        if result.stderr:
            print(result.stderr[-2000:], file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"[spark-submit] {script} timed out after 300s", file=sys.stderr)
    except Exception as exc:
        print(f"[spark-submit] Failed to launch {script}: {exc}", file=sys.stderr)


@app.post("/spark/student-analytics", status_code=202)
def submit_student_analytics(background: BackgroundTasks):
    """Async fire-and-forget submission (for manual curl testing)."""
    run_id = str(uuid.uuid4())
    background.add_task(
        _run_spark_job,
        script="student_analytics.py",
        job_id="spark-student-analytics",
        run_id=run_id,
    )
    return {"status": "submitted", "job": "spark-student-analytics", "run_id": run_id}


@app.post("/spark/student-analytics/run")
def run_student_analytics_sync():
    """
    Run the student analytics PySpark job synchronously.

    Blocks until the job completes, then returns the result.
    Returns HTTP 200 on success, HTTP 500 on failure (with stderr).

    Called by the Airflow DAG so that Spark job failure propagates
    back to Airflow as a real task failure — not a silent background error.

    Example:
        curl -X POST http://localhost:8003/spark/student-analytics/run
    """
    from fastapi import Response

    run_id      = str(uuid.uuid4())
    script_path = os.path.join(SPARK_JOBS_DIR, "student_analytics.py")
    env = os.environ.copy()
    env.update({
        "JOB_ID":        "spark-student-analytics",
        "WEBHOOK_URL":   "http://localhost:8003/webhook/generic",
        "SPARK_LOG_DIR": "/tmp/spark-logs",
    })

    print(f"[spark-submit] SYNC run starting (run_id={run_id})")
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return Response(
            content='{"error":"Spark job timed out after 300s"}',
            status_code=504,
            media_type="application/json",
        )

    stdout_tail = result.stdout[-3000:] if result.stdout else ""
    stderr_tail = result.stderr[-3000:] if result.stderr else ""

    print(f"[spark-submit] SYNC run finished — exit code {result.returncode}")
    if stdout_tail:
        print(stdout_tail)
    if stderr_tail:
        print(stderr_tail, file=sys.stderr)

    if result.returncode != 0:
        # Extract the key error line from stdout (Spark prints it there)
        error_line = next(
            (l for l in result.stdout.splitlines() if "FAILED" in l or "PythonException" in l or "ValueError" in l),
            f"Spark job exited with code {result.returncode}",
        )
        return Response(
            content=__import__("json").dumps({
                "status":    "failed",
                "run_id":    run_id,
                "exit_code": result.returncode,
                "error":     error_line,
                "stdout":    stdout_tail[-1000:],
                "stderr":    stderr_tail[-1000:],
            }),
            status_code=500,
            media_type="application/json",
        )

    return {
        "status":  "success",
        "run_id":  run_id,
        "stdout":  stdout_tail[-500:],
    }


@app.post("/webhook/airflow", status_code=202)
def airflow_webhook(body: AirflowWebhook, x_api_key: Optional[str] = Header(default=None)):
    """
    Accepts Airflow on_failure_callback payloads.

    Airflow config example:
      default_args = {
          "on_failure_callback": lambda ctx: requests.post(
              "http://collector:8003/webhook/airflow",
              headers={"x-api-key": "<your-api-key>"},
              json={
                  "dag_id": ctx["dag"].dag_id,
                  "run_id": ctx["run_id"],
                  "task_id": ctx["task_instance"].task_id,
                  "exception": str(ctx.get("exception", "Unknown error")),
              }
          )
      }
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized access. Kindly provide a valid access key via the x-api-key header.",
        )
    payload = {
        "source": "airflow",
        "job_id": body.dag_id,
        "run_id": body.run_id,
        "task_id": body.task_id,
        "level": "ERROR",
        "timestamp": body.execution_date or _now_iso(),
        "message": body.exception,
        "raw_log_uri": body.log_url,
    }
    try:
        resp = _forward(payload, x_api_key)
    except Exception as e:
        print(f"[webhook] Forward failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to reach ingestion API")
    if resp.status_code == 401:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized access. Kindly provide a valid access key.",
        )
    if resp.status_code not in (200, 202):
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return {"status": "accepted", "run_id": body.run_id}


@app.post("/webhook/generic", status_code=202)
def generic_webhook(body: GenericWebhook, x_api_key: Optional[str] = Header(default=None)):
    """
    Generic webhook — works with any system that can HTTP POST.

    Example curl:
      curl -X POST http://localhost:8003/webhook/generic \\
           -H 'Content-Type: application/json' \\
           -H 'x-api-key: <your-api-key>' \\
           -d '{"pipeline":"my-etl","level":"ERROR","message":"OOM error"}'
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized access. Kindly provide a valid access key via the x-api-key header.",
        )
    run_id = body.run_id or str(uuid.uuid4())
    payload = {
        "source": body.source or "webhook",
        "job_id": body.pipeline,
        "run_id": run_id,
        "level": body.level.upper(),
        "timestamp": body.timestamp or _now_iso(),
        "message": body.message,
    }
    try:
        resp = _forward(payload, x_api_key)
    except Exception as e:
        print(f"[webhook] Forward failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to reach ingestion API")
    if resp.status_code == 401:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized access. Kindly provide a valid access key.",
        )
    if resp.status_code not in (200, 202):
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return {"status": "accepted", "run_id": run_id}
