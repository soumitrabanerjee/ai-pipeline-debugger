"""
Student Grade Analytics Pipeline — PySpark

Simulates a university data engineering job that:
  1. Loads student enrollment records
  2. Loads course grade records (some scores are corrupt: "N/A", "", None)
  3. Joins both datasets and computes department-level stats
  4. Applies a UDF to convert numeric scores → letter grades
  5. Calls .collect() to pull results to the driver

The job FAILS at step 5 — .collect() triggers actual Spark execution,
which hits the UDF on a corrupt score record and raises:

    PythonException: ValueError: could not convert string to float: 'N/A'

This is intentional and realistic: Spark is lazy, so the UDF bug is
invisible until an action (collect/write/show) forces execution.

Integration with AI Pipeline Debugger:
  - Spark ERROR log lines captured by log agent watching /tmp/spark-logs/
  - except block also POSTs the full exception to webhook collector
"""

import os
import sys
import requests
from datetime import datetime, timezone

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, avg, count, udf
from pyspark.sql.types import (
    StructType, StructField,
    IntegerType, StringType, DoubleType,
)

# ── config ────────────────────────────────────────────────────────────────────

WEBHOOK_URL  = os.getenv("WEBHOOK_URL",  "http://localhost:8003/webhook/generic")
JOB_ID       = os.getenv("JOB_ID",       "spark-student-analytics")
LOG_DIR      = os.getenv("SPARK_LOG_DIR", "/tmp/spark-logs")

os.makedirs(LOG_DIR, exist_ok=True)

# ── Spark session ─────────────────────────────────────────────────────────────

spark = (
    SparkSession.builder
    .appName(JOB_ID)
    .master("local[2]")
    .config(
        "spark.driver.extraJavaOptions",
        f"-Dlog4j.configuration=file:{os.path.dirname(os.path.abspath(__file__))}/log4j.properties"
    )
    .getOrCreate()
)
spark.sparkContext.setLogLevel("WARN")


# ── Stage 1: Load student enrollment records ──────────────────────────────────

def load_students():
    print("[analytics] Stage 1 — loading student enrollment records")

    schema = StructType([
        StructField("student_id",  IntegerType(), False),
        StructField("name",        StringType(),  False),
        StructField("department",  StringType(),  False),
        StructField("year",        IntegerType(), False),
        StructField("email",       StringType(),  False),
    ])

    data = [
        (1,  "Alice Johnson",  "Computer Science",  3, "alice@uni.edu"),
        (2,  "Bob Smith",      "Mathematics",       2, "bob@uni.edu"),
        (3,  "Carol White",    "Physics",           4, "carol@uni.edu"),
        (4,  "David Brown",    "Computer Science",  1, "david@uni.edu"),
        (5,  "Eve Davis",      "Mathematics",       3, "eve@uni.edu"),
        (6,  "Frank Miller",   "Physics",           2, "frank@uni.edu"),
        (7,  "Grace Lee",      "Computer Science",  4, "grace@uni.edu"),
        (8,  "Henry Wilson",   "Mathematics",       1, "henry@uni.edu"),
        (9,  "Iris Clark",     "Physics",           3, "iris@uni.edu"),
        (10, "Jack Moore",     "Computer Science",  2, "jack@uni.edu"),
    ]

    df = spark.createDataFrame(data, schema=schema)
    print(f"[analytics] Loaded {df.count()} student records")
    return df


# ── Stage 2: Load grade records (with corrupt entries) ────────────────────────

def load_grades():
    print("[analytics] Stage 2 — loading course grade records")

    schema = StructType([
        StructField("student_id", IntegerType(), False),
        StructField("course",     StringType(),  False),
        StructField("semester",   StringType(),  False),
        StructField("score",      StringType(),  True),   # String — may be corrupt
    ])

    data = [
        (1,  "Algorithms",       "Fall-2025",   "92"),
        (1,  "Databases",        "Fall-2025",   "88"),
        (1,  "OS",               "Spring-2025", "79"),
        (2,  "Calculus II",      "Fall-2025",   "76"),
        (2,  "Linear Algebra",   "Fall-2025",   "N/A"),   # ← corrupt: missing grade
        (2,  "Statistics",       "Spring-2025", "81"),
        (3,  "Quantum Mech",     "Fall-2025",   "95"),
        (3,  "Thermodynamics",   "Fall-2025",   "89"),
        (4,  "Algorithms",       "Fall-2025",   ""),      # ← corrupt: empty string
        (4,  "Databases",        "Spring-2025", "71"),
        (5,  "Calculus II",      "Fall-2025",   "83"),
        (5,  "Statistics",       "Spring-2025", None),    # ← corrupt: null value
        (6,  "Quantum Mech",     "Fall-2025",   "68"),
        (7,  "Algorithms",       "Fall-2025",   "97"),
        (7,  "Databases",        "Spring-2025", "91"),
        (8,  "Calculus II",      "Fall-2025",   "74"),
        (9,  "Thermodynamics",   "Fall-2025",   "85"),
        (10, "Algorithms",       "Spring-2025", "88"),
        (10, "OS",               "Fall-2025",   "INCOMPLETE"),  # ← corrupt: status string
    ]

    df = spark.createDataFrame(data, schema=schema)
    print(f"[analytics] Loaded {df.count()} grade records ({4} with corrupt scores)")
    return df


# ── Stage 3: Join + aggregate ─────────────────────────────────────────────────

def join_and_aggregate(students, grades):
    print("[analytics] Stage 3 — joining datasets and computing department stats")

    joined = students.join(grades, on="student_id", how="inner")

    dept_stats = (
        joined
        .groupBy("department")
        .agg(
            count("student_id").alias("total_grades"),
        )
    )

    dept_stats.show()
    return joined


# ── Stage 4: UDF — score string → letter grade ────────────────────────────────

def score_to_letter(score_str: str) -> str:
    """
    Converts a numeric score string to a letter grade.

    Will raise ValueError for non-numeric strings ("N/A", "", "INCOMPLETE")
    and AttributeError for None values.

    These errors are invisible at transformation time because Spark is lazy.
    They only surface when an ACTION (collect, write, show) triggers execution.
    """
    score = float(score_str)     # ← raises ValueError / AttributeError on corrupt data
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    else:
        return "F"

_grade_udf = udf(score_to_letter, StringType())


def apply_letter_grades(df):
    print("[analytics] Stage 4 — applying letter grade UDF (lazy — no execution yet)")
    # withColumn is a TRANSFORMATION — Spark does NOT execute the UDF here
    return df.withColumn("letter_grade", _grade_udf(col("score")))


# ── Stage 5: Collect to driver ────────────────────────────────────────────────

def collect_to_driver(df):
    print("[analytics] Stage 5 — collecting results to driver")
    print("[analytics] Calling df.collect() — this triggers actual Spark execution")
    print("[analytics] UDF will now run on every row including corrupt score records...")

    # ACTION — triggers full DAG execution including the UDF
    # Fails here when UDF hits score="N/A", score="", score="INCOMPLETE", score=None
    records = df.collect()

    print(f"[analytics] Collected {len(records)} records successfully")
    return records


# ── Failure notification ───────────────────────────────────────────────────────

def notify_failure(exc: Exception):
    message = (
        f"PythonException in UDF 'score_to_letter': failed to convert corrupt score "
        f"values to float during df.collect(). "
        f"Corrupt records found: score='N/A' (student_id=2, Linear Algebra), "
        f"score='' (student_id=4, Algorithms), "
        f"score=None (student_id=5, Statistics), "
        f"score='INCOMPLETE' (student_id=10, OS). "
        f"Root exception: {type(exc).__name__}: {str(exc)[:200]}"
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
        print(f"[analytics] Failure webhook sent → HTTP {resp.status_code}")
    except Exception as e:
        print(f"[analytics] Webhook failed: {e}", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────

def print_run_header():
    """Print timestamped run header and full student roster before Spark starts."""
    now = datetime.now(timezone.utc)
    print("=" * 65)
    print(f"  SPARK JOB  : {JOB_ID}")
    print(f"  START TIME : {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  PIPELINE   : load students → load grades → join → UDF → collect")
    print("=" * 65)

    # Print student roster in a readable table (pure Python, before Spark starts)
    roster = [
        (1,  "Alice Johnson",  "Computer Science",  3),
        (2,  "Bob Smith",      "Mathematics",       2),
        (3,  "Carol White",    "Physics",           4),
        (4,  "David Brown",    "Computer Science",  1),
        (5,  "Eve Davis",      "Mathematics",       3),
        (6,  "Frank Miller",   "Physics",           2),
        (7,  "Grace Lee",      "Computer Science",  4),
        (8,  "Henry Wilson",   "Mathematics",       1),
        (9,  "Iris Clark",     "Physics",           3),
        (10, "Jack Moore",     "Computer Science",  2),
    ]
    print(f"\n{'ID':<5} {'Name':<18} {'Department':<20} {'Year'}")
    print("-" * 55)
    for sid, name, dept, year in roster:
        print(f"  {sid:<4} {name:<18} {dept:<20} Year {year}")
    print(f"\n  Total students : {len(roster)}")
    print(f"  Grade records  : 19  (4 with corrupt scores: N/A, '', None, INCOMPLETE)")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    print_run_header()

    try:
        students  = load_students()
        grades    = load_grades()
        joined    = join_and_aggregate(students, grades)
        with_udf  = apply_letter_grades(joined)
        records   = collect_to_driver(with_udf)   # ← FAILS HERE

        print(f"[analytics] Pipeline completed — {len(records)} student-course records")

    except Exception as exc:
        print(f"\n[analytics] Pipeline FAILED at collect(): {type(exc).__name__}", file=sys.stderr)
        notify_failure(exc)
        spark.stop()
        sys.exit(1)

    finally:
        spark.stop()
