"""
Queue Worker — reads log error events from Redis Streams and runs AI analysis.

Flow:
  Redis stream (log_events)
      │
      ▼
  worker.process_event()
      │
      ├─ calls AI Debugging Engine (:8002/analyze)
      │
      └─ writes Error record to PostgreSQL
"""

import sys
import os
import requests
import redis
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(PROJECT_ROOT)
sys.path.append(os.path.join(PROJECT_ROOT, 'services', 'log-processing-layer'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from services.shared.models import Error
from services.alerting.alerter import send_slack_alert
from parser import extract_error

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://debugger:debugger@localhost:5433/pipeline_debugger")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
AI_ENGINE_URL = os.getenv("AI_ENGINE_URL", "http://localhost:8002/analyze")

STREAM_NAME = "log_events"
GROUP_NAME = "debugger_workers"
CONSUMER_NAME = "worker_1"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def ensure_consumer_group():
    """Create the consumer group if it doesn't exist yet."""
    try:
        redis_client.xgroup_create(STREAM_NAME, GROUP_NAME, id="$", mkstream=True)
        print(f"Created consumer group '{GROUP_NAME}' on stream '{STREAM_NAME}'")
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            print(f"Consumer group '{GROUP_NAME}' already exists — resuming")
        else:
            raise


def analyze_with_ai(message: str, pipeline_context: str | None = None) -> dict:
    """Call the AI Debugging Engine. Returns fallback dict on failure."""
    try:
        response = requests.post(
            AI_ENGINE_URL,
            json={"error_message": message, "pipeline_context": pipeline_context},
            timeout=120,
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"AI analysis failed: {e}")
    return {
        "root_cause": "Analysis Failed (AI Service Unavailable)",
        "suggested_fix": "Check logs manually.",
    }


def process_event(event_id: str, fields: dict):
    """Analyze one error event and upsert the result (no duplicate rows)."""
    job_id = fields.get("job_id", "unknown")
    message = fields.get("message", "")

    print(f"[worker] Processing {event_id} — pipeline={job_id}")

    # Use the log processing layer to parse structured fields from the message
    parsed = extract_error(message)
    error_type = parsed.signature
    pipeline_context = f"Severity: {parsed.severity}\nError summary: {parsed.summary}"

    print(f"[worker] Parsed — error_type='{error_type}' severity='{parsed.severity}'")

    ai_result = analyze_with_ai(message, pipeline_context=pipeline_context)

    db = SessionLocal()
    try:
        # Upsert: update existing row for same pipeline+error_type, else insert
        existing = db.query(Error).filter(
            Error.pipeline_name == job_id,
            Error.error_type == error_type,
        ).first()

        now = datetime.now(timezone.utc).isoformat()

        if existing:
            existing.root_cause = ai_result.get("root_cause", "Pending")
            existing.fix = ai_result.get("suggested_fix", "Pending")
            existing.detected_at = now
            print(f"[worker] Updated existing error '{error_type}' for pipeline '{job_id}'")
        else:
            db.add(Error(
                pipeline_name=job_id,
                error_type=error_type,
                root_cause=ai_result.get("root_cause", "Pending"),
                fix=ai_result.get("suggested_fix", "Pending"),
                detected_at=now,
            ))
            print(f"[worker] Inserted new error '{error_type}' for pipeline '{job_id}'")

        db.commit()
    finally:
        db.close()

    # Send Slack alert (no-op if SLACK_WEBHOOK_URL is not set)
    run_id = fields.get("run_id", "unknown")
    send_slack_alert(
        pipeline_name=job_id,
        run_id=run_id,
        error_type=error_type,
        root_cause=ai_result.get("root_cause", "Unknown"),
        fix=ai_result.get("suggested_fix", "Check logs manually."),
        severity=parsed.severity or "ERROR",
    )


def run():
    ensure_consumer_group()
    print(f"[worker] Listening on stream '{STREAM_NAME}' (group '{GROUP_NAME}')...")

    while True:
        messages = redis_client.xreadgroup(
            GROUP_NAME,
            CONSUMER_NAME,
            {STREAM_NAME: ">"},  # only undelivered messages
            count=1,
            block=5000,          # wait up to 5s before looping
        )

        if not messages:
            continue

        for _stream, events in messages:
            for event_id, fields in events:
                try:
                    process_event(event_id, fields)
                    redis_client.xack(STREAM_NAME, GROUP_NAME, event_id)
                except Exception as e:
                    print(f"[worker] Error processing {event_id}: {e}")
                    # Message stays pending — can be re-claimed on next startup


if __name__ == "__main__":
    run()
