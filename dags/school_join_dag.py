"""
DAG: school_join_example
========================
Compiles SchoolJoinExample.scala into a fat JAR (via sbt) then submits it
with spark-submit.  On any step failure the on_failure callback from
callbacks.py reads the full task log from disk and forwards it to Piplex
for AI root-cause analysis.

Required environment variables:
  SPARK_HOME          — e.g. /opt/spark  (default /opt/spark)
  SCHOOL_JOIN_JOB_DIR — absolute path to the sbt project
                        (default: <repo-root>/spark_jobs/school_join)

Optional:
  PIPLEX_API_KEY      — enables AI log analysis (see callbacks.py)
"""

import os
from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator

from callbacks import on_failure, on_success

# ---------------------------------------------------------------------------
# Paths — override via env vars so this DAG works in any deployment
# ---------------------------------------------------------------------------
SPARK_HOME = os.getenv("SPARK_HOME", "/opt/spark")

# Derive repo root from this file's location (dags/ is one level below root)
_DAG_DIR  = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_DAG_DIR)

JOB_DIR = os.getenv(
    "SCHOOL_JOIN_JOB_DIR",
    os.path.join(_REPO_ROOT, "spark_jobs", "school_join"),
)

# sbt places the JAR at target/school-join.jar (set in build.sbt)
JAR_PATH = os.path.join(JOB_DIR, "target", "school-join.jar")

# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------
default_args = {
    # Fires on failure of ANY task in this DAG — reads the full log from disk
    # and forwards it to Piplex for AI root-cause analysis.
    "on_failure_callback": on_failure,
}

with DAG(
    dag_id="school_join_example",
    default_args=default_args,
    description="Compile & run SchoolJoinExample.scala; collect logs on failure",
    start_date=datetime(2026, 3, 1),
    schedule="@daily",
    catchup=False,
    tags=["spark", "scala"],
) as dag:

    # ------------------------------------------------------------------
    # Step 1 — compile the Scala source into a fat JAR via sbt
    # ------------------------------------------------------------------
    compile_jar = BashOperator(
        task_id="compile_jar",
        bash_command=f"cd '{JOB_DIR}' && sbt package 2>&1",
        # No success callback here; only the final task signals overall success.
    )

    # ------------------------------------------------------------------
    # Step 2 — submit the JAR with spark-submit
    # Stdout/stderr are captured by Airflow and written to the task log,
    # which on_failure will read if this step errors out.
    # ------------------------------------------------------------------
    run_spark_job = BashOperator(
        task_id="run_spark_job",
        bash_command=(
            f"'{SPARK_HOME}/bin/spark-submit' "
            f"--class SchoolJoinExample "
            f"'{JAR_PATH}' "
            f"2>&1"
        ),
        on_success_callback=on_success,
    )

    compile_jar >> run_spark_job
