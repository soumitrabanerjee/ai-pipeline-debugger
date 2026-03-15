"""
Airflow DAG: Pipeline Error Reporter
=====================================
Simulates a Spark pipeline failure and posts the error log
to the AI Pipeline Debugger ingestion API for analysis.

The DAG runs on-demand (no schedule) and performs:
  1. Generates a realistic Spark OOM error payload
  2. POSTs it to the /ingest endpoint
  3. Waits briefly for the AI engine to process
  4. Fetches the debugging solution from the dashboard API
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

import requests
from airflow import DAG
from airflow.operators.python import PythonOperator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PIPELINE_NAME  = "spark-sales-pipeline"
API_KEY        = "dpd_3841dce431b5c1bcfd379177247355f46a9d64a3d38d48cfb988aeb7d88e43c7"
INGESTION_URL  = "https://piplex.in/ingest"
DASHBOARD_URL  = "https://piplex.in/api/dashboard"
WEBHOOK_URL    = "https://piplex.in/webhook/airflow"


def _on_failure(context):
    """Send failure event to PiPlex for AI root-cause analysis."""
    requests.post(
        WEBHOOK_URL,
        headers={"x-api-key": API_KEY},
        json={
            "dag_id":    context["dag"].dag_id,
            "run_id":    context["run_id"],
            "task_id":   context["task_instance"].task_id,
            "exception": str(context.get("exception", "Unknown error")),
        },
        timeout=5,
    )


# A realistic Spark OOM error with a full Java stack trace
SPARK_ERROR_LOG = """\
26/03/16 09:15:42 ERROR Executor: Exception in task 3.0 in stage 12.0 (TID 147)
java.lang.OutOfMemoryError: Java heap space
\tat java.util.Arrays.copyOf(Arrays.java:3236)
\tat java.io.ByteArrayOutputStream.grow(ByteArrayOutputStream.java:118)
\tat java.io.ByteArrayOutputStream.ensureCapacity(ByteArrayOutputStream.java:93)
\tat java.io.ByteArrayOutputStream.write(ByteArrayOutputStream.java:153)
\tat org.apache.spark.util.ByteBufferOutputStream.write(ByteBufferOutputStream.java:41)
\tat java.io.ObjectOutputStream$BlockDataOutputStream.drain(ObjectOutputStream.java:1877)
\tat java.io.ObjectOutputStream$BlockDataOutputStream.setBlockDataMode(ObjectOutputStream.java:1786)
\tat java.io.ObjectOutputStream.writeObject0(ObjectOutputStream.java:1189)
\tat java.io.ObjectOutputStream.writeObject(ObjectOutputStream.java:348)
\tat org.apache.spark.serializer.JavaSerializationStream.writeObject(JavaSerializer.scala:44)
\tat org.apache.spark.shuffle.sort.SortShuffleWriter.write(SortShuffleWriter.scala:71)
\tat org.apache.spark.scheduler.ShuffleMapTask.runTask(ShuffleMapTask.scala:99)
\tat org.apache.spark.scheduler.Task.run(Task.scala:131)
\tat org.apache.spark.executor.Executor$TaskRunner.run(Executor.scala:547)
\tat java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1149)
\tat java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:624)
\tat java.lang.Thread.run(Thread.java:750)
Caused by: org.apache.spark.SparkException: Task 3 in stage 12.0 failed 4 times, most recent failure: Lost task 3.3 in stage 12.0 (TID 147)
\tat org.apache.spark.scheduler.DAGScheduler.handleTaskCompletion(DAGScheduler.scala:1682)
\tat org.apache.spark.scheduler.DAGScheduler$$anonfun$handleTaskCompletion$1.apply(DAGScheduler.scala:1289)
"""

# ---------------------------------------------------------------------------
# DAG default args
# ---------------------------------------------------------------------------
default_args = {
    "owner": "data-engineering",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}


# ---------------------------------------------------------------------------
# Task functions
# ---------------------------------------------------------------------------
def generate_error_payload(**context):
    """Build the LogEvent JSON that the ingestion API expects."""
    run_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    payload = {
        "source": "spark",
        "workspace_id": "self",  # overridden server-side using the API key
        "job_id": PIPELINE_NAME,
        "run_id": run_id,
        "task_id": "transform_aggregate_sales",
        "level": "ERROR",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "message": SPARK_ERROR_LOG,
        "raw_log_uri": f"s3://pipeline-logs/{PIPELINE_NAME}/{run_id}/executor-3.log",
    }

    context["ti"].xcom_push(key="error_payload", value=payload)
    context["ti"].xcom_push(key="run_id", value=run_id)

    print(f"[INFO] Generated error payload for run_id={run_id}")
    print(f"[INFO] Pipeline: {PIPELINE_NAME}")
    print(f"[INFO] Error type: java.lang.OutOfMemoryError")
    return payload


def post_error_to_ingestion(**context):
    """POST the error payload to the AI Pipeline Debugger ingestion API."""
    payload = context["ti"].xcom_pull(
        task_ids="generate_error_payload", key="error_payload"
    )
    run_id = context["ti"].xcom_pull(
        task_ids="generate_error_payload", key="run_id"
    )

    headers = {
        "Content-Type": "application/json",
        "x-api-key": API_KEY,
    }

    print(f"[INFO] Posting error to {INGESTION_URL}")
    print(f"[INFO] run_id={run_id}")

    response = requests.post(INGESTION_URL, json=payload, headers=headers, timeout=30)

    print(f"[INFO] Response status: {response.status_code}")
    print(f"[INFO] Response body:   {response.text}")

    if response.status_code not in (200, 202):
        raise Exception(
            f"Ingestion API returned {response.status_code}: {response.text}"
        )

    context["ti"].xcom_push(key="ingestion_response", value=response.json())
    return response.json()


def wait_for_processing(**context):
    """Give the AI engine time to process the error through the full pipeline."""
    import time

    run_id = context["ti"].xcom_pull(
        task_ids="generate_error_payload", key="run_id"
    )
    print(f"[INFO] Waiting 15 seconds for AI engine to process run_id={run_id} ...")
    time.sleep(15)
    print("[INFO] Done waiting — proceeding to fetch results.")


def fetch_debugging_solution(**context):
    """Retrieve the AI-generated debugging solution from the dashboard API."""
    headers = {"x-api-key": API_KEY}

    print(f"[INFO] Fetching dashboard from {DASHBOARD_URL}")
    response = requests.get(DASHBOARD_URL, headers=headers, timeout=30)

    print(f"[INFO] Response status: {response.status_code}")

    if response.status_code != 200:
        raise Exception(
            f"Dashboard API returned {response.status_code}: {response.text}"
        )

    data = response.json()

    matching_errors = [
        e for e in data.get("errors", []) if e.get("pipeline") == PIPELINE_NAME
    ]

    if matching_errors:
        latest = matching_errors[0]
        print("=" * 70)
        print("  AI DEBUGGING SOLUTION")
        print("=" * 70)
        print(f"  Pipeline:    {latest.get('pipeline')}")
        print(f"  Error:       {latest.get('error')}")
        print(f"  Root Cause:  {latest.get('rootCause', 'N/A')}")
        print(f"  Fix:         {latest.get('fix', 'N/A')}")
        print(f"  Detected At: {latest.get('detectedAt', 'N/A')}")
        print("=" * 70)
        context["ti"].xcom_push(key="solution", value=latest)
    else:
        print(f"[WARN] No errors found yet for pipeline '{PIPELINE_NAME}'.")
        print(f"[INFO] Full dashboard response: {json.dumps(data, indent=2)}")

    return data


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------
with DAG(
    dag_id="pipeline_error_debugger",
    default_args={**default_args, "on_failure_callback": _on_failure},
    description="Posts a simulated Spark OOM error and retrieves the AI debugging solution",
    schedule=None,  # Manual trigger only
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["debugging", "ai-pipeline-debugger", "spark"],
) as dag:

    t_generate = PythonOperator(
        task_id="generate_error_payload",
        python_callable=generate_error_payload,
    )

    t_post = PythonOperator(
        task_id="post_error_to_ingestion",
        python_callable=post_error_to_ingestion,
    )

    t_wait = PythonOperator(
        task_id="wait_for_processing",
        python_callable=wait_for_processing,
    )

    t_fetch = PythonOperator(
        task_id="fetch_debugging_solution",
        python_callable=fetch_debugging_solution,
    )

    t_generate >> t_post >> t_wait >> t_fetch
