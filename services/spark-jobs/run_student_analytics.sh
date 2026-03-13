#!/bin/bash
# Runs the Student Grade Analytics PySpark job wired to the AI Pipeline Debugger.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AGENT="$REPO_ROOT/services/log-collection-layer/agent.py"
LOG_DIR="/tmp/spark-logs"
JOB_ID="spark-student-analytics"

mkdir -p "$LOG_DIR"

echo "[runner] Starting log agent watching $LOG_DIR..."
python3 "$AGENT" \
  --watch-dir  "$LOG_DIR" \
  --job-id     "$JOB_ID" \
  --ingest-url "http://localhost:8000/ingest" \
  > /tmp/student-log-agent.log 2>&1 &
AGENT_PID=$!
echo "[runner] Log agent PID: $AGENT_PID"

sleep 1

echo "[runner] Launching PySpark student analytics job..."
JOB_ID="$JOB_ID" \
WEBHOOK_URL="http://localhost:8003/webhook/generic" \
SPARK_LOG_DIR="$LOG_DIR" \
  python3 "$SCRIPT_DIR/student_analytics.py"

sleep 3
kill "$AGENT_PID" 2>/dev/null || true
echo "[runner] Done. Check dashboard at http://localhost:5173"
