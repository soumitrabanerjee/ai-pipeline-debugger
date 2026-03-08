"""
Log Simulator — writes realistic Spark / Airflow / dbt log lines to a
directory so the file-watching agent has something to process in dev/demo.

Usage:
  # Generate a burst of Spark logs with one ERROR:
  python simulator.py --type spark --job-id spark-etl-prod --errors 1

  # Stream continuous Airflow logs (one line every 2s):
  python simulator.py --type airflow --job-id customer_etl --interval 2 --continuous

  # Write 10 dbt lines to a specific directory:
  python simulator.py --type dbt --job-id dbt-staging --count 10 --out-dir /tmp/my-logs
"""

import os
import sys
import time
import uuid
import random
import argparse
from datetime import datetime, timezone

# ── log templates ─────────────────────────────────────────────────────────────

_SPARK_INFO = [
    "SparkContext: Running Spark version 3.5.0",
    "DAGScheduler: Submitting 4 missing tasks from stage 12",
    "TaskSetManager: Finished task 3.0 in stage 12.0 (TID 42) in 1234 ms",
    "BlockManager: Using org.apache.spark.storage.RandomBlockReplicationPolicy",
    "MemoryStore: Block broadcast_5 stored as values in memory",
    "SparkUI: Bound SparkUI to 0.0.0.0, port 4040",
]

_SPARK_ERROR = [
    "ExecutorLostFailure: Executor 5 exited caused by one of the running tasks",
    "OutOfMemoryError: Java heap space — executor memory exceeded (configured: 4g)",
    "FetchFailedException: Failed to fetch shuffle data from BlockManager",
    "TaskKilledException: task killed due to stage cancellation",
    "SparkException: Job aborted due to stage failure: Task 12 failed 4 times",
    "AnalysisException: cannot resolve 'user_id' given input columns: [id, name]",
]

_AIRFLOW_INFO = [
    "taskinstance.py:1234 INFO - Dependencies all met for <TaskInstance: customer_etl.extract_data>",
    "taskinstance.py:1001 INFO - Starting attempt 1 of 1",
    "taskinstance.py:1200 INFO - Executing <Task(PythonOperator): transform_data>",
    "taskinstance.py:1400 INFO - Task exited with return code 0",
    "scheduler_job.py:742 INFO - 3 tasks up for execution",
]

_AIRFLOW_ERROR = [
    "taskinstance.py:1456 ERROR - Task failed with exception\nTraceback: AirflowException: Bash command failed",
    "taskinstance.py:1456 ERROR - DagRunAlreadyExists: A DagRun b'scheduled__2026-03-08' already exists",
    "taskinstance.py:1456 ERROR - OperationalError: could not connect to server: Connection refused",
    "taskinstance.py:1456 ERROR - SLAMissed: customer_etl missed SLA for task extract_data",
]

_DBT_INFO = [
    "Running dbt with args: ['run', '--project-dir', '/app']",
    "Found 24 models, 6 tests, 0 snapshots, 0 analyses",
    "Completed successfully — Done. PASS=23 WARN=1 ERROR=0 SKIP=0 TOTAL=24",
    "model.jaffle_shop.customers ... OK  [SELECT 1234 rows in 0.45s]",
]

_DBT_ERROR = [
    "Compilation Error in model customers: column 'email_hash' does not exist",
    "Database Error in model orders: relation 'raw.orders' does not exist",
    "dbt found 1 failures while testing model stg_customers",
    "Runtime Error: Could not connect to database: FATAL password authentication failed",
]

_TEMPLATES = {
    "spark":   (_SPARK_INFO,   _SPARK_ERROR,   _spark_line),
    "airflow": (_AIRFLOW_INFO, _AIRFLOW_ERROR, _airflow_line),
    "dbt":     (_DBT_INFO,     _DBT_ERROR,     _dbt_line),
}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _spark_line(level: str, message: str) -> str:
    return f"{_ts()} {level} {message}"


def _airflow_line(level: str, message: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    if level == "ERROR":
        return f"[{ts}] {{{message}}}"
    return f"[{ts}] {{{message}}}"


def _dbt_line(level: str, message: str) -> str:
    prefix = "ERROR" if level == "ERROR" else "INFO "
    return f"{_ts()}  {prefix}  {message}"


# late-bind so the functions above are defined first
_TEMPLATES = {
    "spark":   (_SPARK_INFO,   _SPARK_ERROR,   _spark_line),
    "airflow": (_AIRFLOW_INFO, _AIRFLOW_ERROR, _airflow_line),
    "dbt":     (_DBT_INFO,     _DBT_ERROR,     _dbt_line),
}


# ── writer ────────────────────────────────────────────────────────────────────

def generate_lines(log_type: str, total: int, num_errors: int) -> list[str]:
    info_msgs, error_msgs, formatter = _TEMPLATES[log_type]
    lines = []
    error_positions = set(random.sample(range(total), min(num_errors, total)))

    for i in range(total):
        if i in error_positions:
            msg = random.choice(error_msgs)
            lines.append(formatter("ERROR", msg))
        else:
            msg = random.choice(info_msgs)
            lines.append(formatter("INFO", msg))

    return lines


def write_log_file(out_dir: str, job_id: str, lines: list[str]) -> str:
    os.makedirs(out_dir, exist_ok=True)
    run_id = str(uuid.uuid4())[:8]
    filename = f"{job_id}_{run_id}.log"
    path = os.path.join(out_dir, filename)
    with open(path, "w") as fh:
        for line in lines:
            fh.write(line + "\n")
    return path


def stream_to_file(path: str, lines: list[str], interval: float):
    """Append lines one at a time with a delay (simulates real-time tailing)."""
    with open(path, "a") as fh:
        for line in lines:
            fh.write(line + "\n")
            fh.flush()
            print(f"  [sim] wrote: {line[:80]}")
            time.sleep(interval)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Pipeline Log Simulator")
    parser.add_argument("--type",       default="spark", choices=["spark", "airflow", "dbt"])
    parser.add_argument("--job-id",     default="sim-pipeline")
    parser.add_argument("--count",      type=int, default=20, help="Total log lines per file")
    parser.add_argument("--errors",     type=int, default=2,  help="Number of ERROR lines")
    parser.add_argument("--out-dir",    default="/tmp/pipeline-logs")
    parser.add_argument("--interval",   type=float, default=0.5, help="Seconds between lines (streaming mode)")
    parser.add_argument("--continuous", action="store_true", help="Keep generating files indefinitely")
    args = parser.parse_args()

    print(f"[sim] type={args.type} job={args.job_id} out={args.out_dir}")

    while True:
        lines = generate_lines(args.type, args.count, args.errors)
        path = write_log_file(args.out_dir, args.job_id, [])  # create empty file first
        print(f"[sim] Streaming {len(lines)} lines → {path}")
        stream_to_file(path, lines, args.interval)
        print(f"[sim] Done writing {path}")

        if not args.continuous:
            break

        pause = random.uniform(5, 15)
        print(f"[sim] Sleeping {pause:.1f}s before next run...")
        time.sleep(pause)


if __name__ == "__main__":
    main()
