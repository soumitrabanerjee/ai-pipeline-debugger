"""
Shared webhook callbacks for all DAGs.

Drop this file in the same Airflow dags/ folder alongside the DAG files.

Environment variable:
  PIPELINE_DEBUGGER_URL  — base URL of the webhook-collector
                           default: http://localhost:8003
"""

import os
import requests

WEBHOOK_BASE = os.getenv("PIPELINE_DEBUGGER_URL", "http://localhost:8003")
WEBHOOK_URL  = f"{WEBHOOK_BASE}/webhook/airflow"


def _post(payload: dict):
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"[debugger] webhook failed: {e}")


def on_failure(context):
    _post({
        "dag_id":         context["dag"].dag_id,
        "run_id":         context["run_id"],
        "task_id":        context["task_instance"].task_id,
        "state":          "failed",
        "execution_date": str(context.get("execution_date", "")),
        "exception":      str(context.get("exception", "Task failed")),
        "log_url":        context["task_instance"].log_url,
    })


def on_success(context):
    _post({
        "dag_id":         context["dag"].dag_id,
        "run_id":         context["run_id"],
        "task_id":        context["task_instance"].task_id,
        "state":          "success",
        "execution_date": str(context.get("execution_date", "")),
    })
