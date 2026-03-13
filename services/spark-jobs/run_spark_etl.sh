#!/bin/bash
# Runs the PySpark Customer LTV ETL job wired to the AI Pipeline Debugger.
#
# What this does:
#   1. Starts the log agent watching /tmp/spark-logs — captures Spark ERROR lines
#   2. Runs customer_etl.py — fails with ZeroDivisionError in the LTV UDF
#   3. The job's except block POSTs the exception to the webhook collector
#   4. Both paths feed the ingestion API → Redis → AI engine → dashboard

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AGENT="$REPO_ROOT/services/log-collection-layer/agent.py"
LOG_DIR="/tmp/spark-logs"
JOB_ID="spark-customer-ltv-etl"

mkdir -p "$LOG_DIR"

# ── 1. Start log agent ────────────────────────────────────────────────────────
echo "[runner] Starting log agent for '$JOB_ID'..."
python3 "$AGENT" \
  --watch-dir "$LOG_DIR" \
  --job-id    "$JOB_ID" \
  --ingest-url "http://localhost:8000/ingest" \
  > /tmp/spark-log-agent.log 2>&1 &
AGENT_PID=$!
echo "[runner] Log agent PID: $AGENT_PID"

sleep 1   # give the agent time to set up its file watchers

# ── 2. Run the Spark job ───────────────────────────────────────────────────────
echo "[runner] Launching PySpark job..."
JOB_ID="$JOB_ID" \
WEBHOOK_URL="http://localhost:8003/webhook/generic" \
SPARK_LOG_DIR="$LOG_DIR" \
  python3 "$SCRIPT_DIR/customer_etl.py"
JOB_EXIT=$?

# ── 3. Let agent flush any final lines ────────────────────────────────────────
sleep 3
kill "$AGENT_PID" 2>/dev/null || true

echo ""
echo "[runner] Job exited with code $JOB_EXIT"
echo "[runner] Spark log: $LOG_DIR/${JOB_ID}.log"
echo "[runner] Agent log: /tmp/spark-log-agent.log"
echo "[runner] Dashboard: http://localhost:5173"
