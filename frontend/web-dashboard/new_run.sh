#!/bin/bash
# Sends a sample ERROR log event to the ingestion API.
# The ingestion API returns 202 immediately and publishes to Redis.
# The queue worker picks it up asynchronously and runs AI analysis.

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
JOB_ID="spark-etl-$(date +%H%M)"

echo "Sending ERROR log event for pipeline: $JOB_ID"

curl -s -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d "{
    \"source\": \"spark\",
    \"workspace_id\": \"data-team\",
    \"job_id\": \"$JOB_ID\",
    \"run_id\": \"run-$(date +%s)\",
    \"level\": \"ERROR\",
    \"timestamp\": \"$TIMESTAMP\",
    \"message\": \"ExecutorLostFailure: Spark executor 3 exited due to OutOfMemoryError. Increase spark.executor.memory.\"
  }" | python3 -m json.tool

echo ""
echo "Event queued. The worker will run AI analysis and save results to the DB."
echo "Check the dashboard at http://localhost:5173 in a few seconds."
