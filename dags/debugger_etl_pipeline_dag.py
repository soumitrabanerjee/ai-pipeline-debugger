from datetime import datetime
from airflow import DAG
from airflow.operators.bash import BashOperator
from callbacks import on_failure, on_success

default_args = {
    "on_failure_callback": on_failure,
    "on_success_callback": on_success,
}

with DAG(
    dag_id="debugger_etl_pipeline",
    default_args=default_args,
    start_date=datetime(2026, 3, 1),
    schedule="@hourly",
    catchup=False,
) as dag:
    BashOperator(
        task_id="run_debugger_etl",
        bash_command="echo 'debugger_etl_pipeline run at $(date)'",
    )
