from datetime import datetime
from airflow import DAG
from airflow.operators.bash import BashOperator
from callbacks import on_failure, on_success

import os
REPO_ROOT = os.getenv("PIPELINE_DEBUGGER_REPO", "/opt/ai-pipeline-debugger")

default_args = {
    "on_failure_callback": on_failure,
    "on_success_callback": on_success,
}

with DAG(
    dag_id="spark-customer-ltv-etl",
    default_args=default_args,
    start_date=datetime(2026, 3, 1),
    schedule="@daily",
    catchup=False,
) as dag:
    BashOperator(
        task_id="run_customer_ltv_etl",
        bash_command=f"python3 {REPO_ROOT}/services/spark-jobs/customer_etl.py",
        env={
            "JOB_ID": "spark-customer-ltv-etl",
            "WEBHOOK_URL": "{{ var.value.get('PIPELINE_DEBUGGER_URL', 'http://localhost:8003') }}/webhook/generic",
            "SPARK_LOG_DIR": "/tmp/spark-logs",
        },
    )
