"""
PySpark Job: Pipeline Error Debugger
======================================
A Spark job that:
  1. Generates a simulated Spark error event (schema mismatch)
  2. Posts the error to the AI Pipeline Debugger ingestion API
  3. Waits for AI processing
  4. Retrieves the AI-generated root cause and fix
  5. Stores the results in a Spark DataFrame for further analysis

Run with:
  spark-submit --master local[*] spark_jobs/debug_pipeline_errors.py

Or import and use the helper functions from another Spark job.
"""

import json
import time
import uuid
from datetime import datetime

import requests
from pyspark.sql import SparkSession
from pyspark.sql.types import (
    FloatType,
    StringType,
    StructField,
    StructType,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
INGESTION_URL = "http://localhost:8000/ingest"
DASHBOARD_URL = "http://localhost:8001/dashboard"
ERRORS_URL = "http://localhost:8001/pipelines/{pipeline_name}/errors"
API_KEY = "dpd_6d9fafed8bd77bb637a12aefb6f32ac08daa4ed48cf50edbbb31b64cdd831233"

PIPELINE_NAME = "customer_churn_model"

# ---------------------------------------------------------------------------
# Simulated error: a PySpark schema mismatch with a nested Caused-by chain
# ---------------------------------------------------------------------------
PYSPARK_ERROR_LOG = """\
Traceback (most recent call last):
  File "/opt/spark/jobs/customer_churn_model.py", line 87, in transform_features
    df_joined = df_customers.join(df_transactions, "customer_id")
  File "/opt/spark/python/pyspark/sql/dataframe.py", line 1583, in join
    jdf = self._jdf.join(other._jdf, on, how)
py4j.protocol.Py4JJavaError: An error occurred while calling o245.join.
: org.apache.spark.sql.AnalysisException: Cannot resolve column name "customer_id" among [cust_id, name, email, signup_date, plan_tier];
\tat org.apache.spark.sql.Dataset.resolve(Dataset.scala:301)
\tat org.apache.spark.sql.Dataset.join(Dataset.scala:1098)
Caused by: org.apache.spark.sql.catalyst.analysis.UnresolvedException: Column 'customer_id' does not exist. Available columns: [cust_id, name, email, signup_date, plan_tier]
\tat org.apache.spark.sql.catalyst.analysis.CheckAnalysis.failAnalysis(CheckAnalysis.scala:51)
\tat org.apache.spark.sql.catalyst.analysis.Analyzer$ResolveReferences$$anonfun$apply$1.applyOrElse(Analyzer.scala:1027)

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/opt/spark/jobs/customer_churn_model.py", line 142, in main
    result = transform_features(spark, config)
  File "/opt/spark/jobs/customer_churn_model.py", line 87, in transform_features
    df_joined = df_customers.join(df_transactions, "customer_id")
pyspark.sql.utils.AnalysisException: Cannot resolve column name "customer_id" among [cust_id, name, email, signup_date, plan_tier]
"""


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def create_spark_session(app_name: str = "PipelineErrorDebugger") -> SparkSession:
    """Create or get an existing SparkSession."""
    return (
        SparkSession.builder
        .appName(app_name)
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )


def generate_error_event(pipeline_name: str, error_message: str) -> dict:
    """Build a LogEvent payload matching the ingestion API schema."""
    run_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    return {
        "source": "spark",
        "workspace_id": "1",
        "job_id": pipeline_name,
        "run_id": run_id,
        "task_id": "transform_features",
        "level": "ERROR",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "message": error_message,
        "raw_log_uri": f"s3://pipeline-logs/{pipeline_name}/{run_id}/driver.log",
    }


def post_error(event: dict) -> dict:
    """POST the error event to the ingestion API and return the response."""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": API_KEY,
    }
    print(f"[Spark] Posting error for pipeline='{event['job_id']}', run_id='{event['run_id']}'")
    resp = requests.post(INGESTION_URL, json=event, headers=headers, timeout=30)
    print(f"[Spark] Ingestion response: {resp.status_code} — {resp.text}")

    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Ingestion failed with {resp.status_code}: {resp.text}")

    return resp.json()


def fetch_pipeline_errors(pipeline_name: str) -> list[dict]:
    """GET errors for a specific pipeline from the API layer."""
    url = ERRORS_URL.format(pipeline_name=pipeline_name)
    headers = {"x-api-key": API_KEY}

    print(f"[Spark] Fetching errors from {url}")
    resp = requests.get(url, headers=headers, timeout=30)
    print(f"[Spark] Errors response: {resp.status_code}")

    if resp.status_code != 200:
        raise RuntimeError(f"Errors API returned {resp.status_code}: {resp.text}")

    return resp.json()


def fetch_dashboard() -> dict:
    """GET the full dashboard (all pipelines + all errors)."""
    headers = {"x-api-key": API_KEY}
    resp = requests.get(DASHBOARD_URL, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Dashboard API returned {resp.status_code}: {resp.text}")
    return resp.json()


def errors_to_dataframe(spark: SparkSession, errors: list[dict]):
    """Convert API error responses into a Spark DataFrame."""
    schema = StructType([
        StructField("pipeline", StringType(), True),
        StructField("error", StringType(), True),
        StructField("rootCause", StringType(), True),
        StructField("fix", StringType(), True),
        StructField("detectedAt", StringType(), True),
    ])

    rows = [
        (
            e.get("pipeline", ""),
            e.get("error", ""),
            e.get("rootCause", ""),
            e.get("fix", ""),
            e.get("detectedAt", ""),
        )
        for e in errors
    ]

    return spark.createDataFrame(rows, schema=schema)


# ---------------------------------------------------------------------------
# Main job
# ---------------------------------------------------------------------------

def main():
    spark = create_spark_session()

    print("=" * 70)
    print("  STEP 1: Generate & post a simulated Spark error")
    print("=" * 70)

    event = generate_error_event(PIPELINE_NAME, PYSPARK_ERROR_LOG)
    ingestion_result = post_error(event)
    print(f"[Spark] Accepted: {json.dumps(ingestion_result, indent=2)}")

    print("\n" + "=" * 70)
    print("  STEP 2: Wait for AI pipeline to process the error")
    print("=" * 70)

    wait_seconds = 20
    print(f"[Spark] Waiting {wait_seconds}s for the AI debugging engine ...")
    time.sleep(wait_seconds)

    print("\n" + "=" * 70)
    print("  STEP 3: Fetch the AI-generated debugging solution")
    print("=" * 70)

    # Try pipeline-specific errors first, fall back to dashboard
    try:
        errors = fetch_pipeline_errors(PIPELINE_NAME)
    except RuntimeError:
        print("[Spark] Pipeline errors endpoint unavailable, trying dashboard ...")
        dashboard = fetch_dashboard()
        errors = [
            e for e in dashboard.get("errors", [])
            if e.get("pipeline") == PIPELINE_NAME
        ]

    if errors:
        print(f"\n[Spark] Found {len(errors)} error(s) for '{PIPELINE_NAME}':\n")
        for i, err in enumerate(errors, 1):
            print(f"  --- Error #{i} ---")
            print(f"  Type:        {err.get('error', 'N/A')}")
            print(f"  Root Cause:  {err.get('rootCause', 'N/A')}")
            print(f"  Suggested Fix: {err.get('fix', 'N/A')}")
            print(f"  Detected At: {err.get('detectedAt', 'N/A')}")
            print()
    else:
        print(f"[Spark] No errors found yet for '{PIPELINE_NAME}'. "
              "The AI engine may still be processing.")

    print("=" * 70)
    print("  STEP 4: Load results into a Spark DataFrame")
    print("=" * 70)

    df_errors = errors_to_dataframe(spark, errors)
    df_errors.show(truncate=60)
    df_errors.printSchema()

    # Example: filter for high-priority schema errors
    df_schema_errors = df_errors.filter(
        df_errors.error.contains("SCHEMA") | df_errors.error.contains("MISSING_KEY")
    )
    schema_count = df_schema_errors.count()
    print(f"[Spark] Schema-related errors: {schema_count}")

    if schema_count > 0:
        print("[Spark] Schema errors found — printing fixes:")
        df_schema_errors.select("pipeline", "error", "fix").show(truncate=80)

    print("\n[Spark] Job complete.")
    spark.stop()


if __name__ == "__main__":
    main()
