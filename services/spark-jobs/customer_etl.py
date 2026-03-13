"""
Customer LTV ETL — PySpark job

Pipeline stages:
  1. Extract  — build synthetic customer + transaction records in-memory
  2. Transform — compute lifetime value (LTV) per customer via a UDF
                 FAILS: some customers have monthly_churn_rate=0.0
                        → ZeroDivisionError inside the UDF
                        → Spark wraps it in a PythonException and aborts
  3. Load     — write results to Parquet (never reached)

Integration with AI Pipeline Debugger
  - Spark ERROR lines are captured by the log agent watching the log directory
  - The except block also POSTs the full exception to the webhook collector
    so the AI engine gets rich context even if the agent misses a line
"""

import os
import sys
import requests
from datetime import datetime, timezone

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, udf
from pyspark.sql.types import (
    StructType, StructField,
    StringType, FloatType, IntegerType, DoubleType,
)

# ── config ────────────────────────────────────────────────────────────────────

WEBHOOK_URL  = os.getenv("WEBHOOK_URL",  "http://localhost:8003/webhook/generic")
JOB_ID       = os.getenv("JOB_ID",       "spark-customer-ltv-etl")
LOG_DIR      = os.getenv("SPARK_LOG_DIR", "/tmp/spark-logs")

os.makedirs(LOG_DIR, exist_ok=True)


# ── Spark session ─────────────────────────────────────────────────────────────

spark = (
    SparkSession.builder
    .appName(JOB_ID)
    .master("local[2]")
    .config("spark.sql.execution.arrow.pyspark.enabled", "false")
    # Route Spark logs to a file the agent can watch
    .config("spark.driver.extraJavaOptions",
            f"-Dlog4j.configuration=file:{os.path.dirname(__file__)}/log4j.properties")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("WARN")


# ── Stage 1: Extract ──────────────────────────────────────────────────────────

def extract():
    print("[etl] Stage 1: Extract — loading customer and transaction data")

    customer_schema = StructType([
        StructField("customer_id",          StringType(),  False),
        StructField("segment",              StringType(),  False),
        StructField("avg_monthly_revenue",  FloatType(),   False),
        StructField("monthly_churn_rate",   FloatType(),   False),   # 0.0 for some rows → UDF bomb
        StructField("tenure_months",        IntegerType(), False),
    ])

    customers = [
        ("C001", "enterprise", 45_000.0,  0.05,  36),
        ("C002", "smb",         8_500.0,  0.12,  18),
        ("C003", "enterprise", 62_000.0,  0.00,  48),   # churn_rate=0 → will fail
        ("C004", "startup",     1_200.0,  0.25,   6),
        ("C005", "smb",         9_800.0,  0.00,  24),   # churn_rate=0 → will fail
        ("C006", "enterprise", 38_000.0,  0.03,  60),
        ("C007", "startup",       900.0,  0.30,   3),
    ]

    return spark.createDataFrame(customers, schema=customer_schema)


# ── Stage 2: Transform ────────────────────────────────────────────────────────

def _compute_ltv(avg_revenue: float, churn_rate: float) -> float:
    """
    LTV = average monthly revenue / monthly churn rate.
    Raises ZeroDivisionError for customers with churn_rate == 0.
    In production this should guard against zero, but here it doesn't.
    """
    return float(avg_revenue) / float(churn_rate)   # ← intentional failure

_ltv_udf = udf(_compute_ltv, DoubleType())


def transform(customers):
    print("[etl] Stage 2: Transform — computing LTV per customer")

    enriched = customers.withColumn(
        "lifetime_value_usd",
        _ltv_udf(col("avg_monthly_revenue"), col("monthly_churn_rate")),
    )

    # Trigger execution — Spark is lazy; the UDF only runs on .show()/.write
    enriched.show(truncate=False)
    return enriched


# ── Stage 3: Load ─────────────────────────────────────────────────────────────

def load(df):
    output_path = os.path.join(LOG_DIR, "customer_ltv_output")
    print(f"[etl] Stage 3: Load — writing results to {output_path}")
    df.write.mode("overwrite").parquet(output_path)
    print("[etl] Load complete.")


# ── Failure notification ───────────────────────────────────────────────────────

def _notify_failure(exc: Exception):
    """POST the exception to the webhook collector (fire-and-forget)."""
    message = (
        f"PythonException in UDF '_compute_ltv': ZeroDivisionError: "
        f"float division by zero. "
        f"Customer records with monthly_churn_rate=0.0 cannot compute LTV. "
        f"Affected segment: enterprise (C003), smb (C005). "
        f"Original: {type(exc).__name__}: {exc}"
    )
    try:
        resp = requests.post(
            WEBHOOK_URL,
            json={
                "pipeline":  JOB_ID,
                "level":     "ERROR",
                "message":   message,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            timeout=5,
        )
        print(f"[etl] Failure webhook sent → HTTP {resp.status_code}")
    except Exception as e:
        print(f"[etl] Webhook failed (collector not running?): {e}", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"[etl] Starting {JOB_ID} at {datetime.now(timezone.utc).isoformat()}")
    try:
        customers = extract()
        enriched  = transform(customers)   # ← raises here
        load(enriched)
        print("[etl] Pipeline completed successfully.")
    except Exception as exc:
        print(f"[etl] Pipeline FAILED: {exc}", file=sys.stderr)
        _notify_failure(exc)
        spark.stop()
        sys.exit(1)
    finally:
        spark.stop()
