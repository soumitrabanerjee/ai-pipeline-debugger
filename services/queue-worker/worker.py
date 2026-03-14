"""
Queue Worker — reads log error events from Redis Streams and runs AI analysis.

Flow:
  Redis stream (log_events)
      │
      ▼
  worker.process_event()
      │
      ├─ 0. scrub PII / secrets
      ├─ 1. parse error structure (log-processing-layer)
      ├─ 2. embed error message   (ai-engine /embed)
      ├─ 3. retrieve similar past incidents via pgvector  (ai-engine /retrieve)
      ├─ 4. analyse with Claude + RAG context  (ai-engine /analyze)
      ├─ 4b. Root Cause Engine — build_hypotheses() + select_top()
      ├─ 5. upsert Error record + embedding to PostgreSQL
      └─ 6. multi-channel alerts (Slack / Teams / Email / PagerDuty)
"""

import sys
import os
import requests
import redis
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(PROJECT_ROOT)
sys.path.append(os.path.join(PROJECT_ROOT, 'services', 'log-processing-layer'))
sys.path.append(os.path.join(PROJECT_ROOT, 'services', 'root-cause-engine'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from services.shared.models import Error
from services.shared.scrubber import scrub
from services.alerting.alerter import send_alerts
from parser import extract_error
from engine import build_hypotheses, select_top

DATABASE_URL   = os.getenv("DATABASE_URL",   "postgresql://debugger:debugger@localhost:5433/pipeline_debugger")
REDIS_URL      = os.getenv("REDIS_URL",      "redis://localhost:6379")
AI_ENGINE_URL  = os.getenv("AI_ENGINE_URL",  "http://localhost:8002")   # base URL, no trailing slash

STREAM_NAME   = "log_events"
GROUP_NAME    = "debugger_workers"
CONSUMER_NAME = "worker_1"

# Minimum cosine similarity to include an incident in RAG context (0–1 scale)
RAG_SIMILARITY_THRESHOLD = 0.75

engine       = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)


# ── AI engine helpers ──────────────────────────────────────────────────────────

def embed_error(message: str) -> list[float] | None:
    """Call ai-engine /embed to get a 384-dim vector. Returns None on failure."""
    try:
        r = requests.post(
            f"{AI_ENGINE_URL}/embed",
            json={"text": message},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json().get("embedding")
    except Exception as e:
        print(f"[worker] Embed call failed: {e}")
    return None


def retrieve_similar(
    embedding: list[float], workspace_id: str, k: int = 5
) -> tuple[list[str], list[str]]:
    """
    Dual-source KNN retrieval from pgvector:
      - Source 1: similar past error incidents from the errors table
      - Source 2: relevant runbook sections from runbook_chunks

    Both sources are filtered by RAG_SIMILARITY_THRESHOLD (0.75 cosine).
    Returns (similar_incidents, runbook_sections) — both are lists of
    formatted strings ready for the Claude prompt.
    Returns ([], []) on failure — RAG degrades gracefully to standard prompt.
    """
    try:
        r = requests.post(
            f"{AI_ENGINE_URL}/retrieve",
            json={"embedding": embedding, "workspace_id": workspace_id, "k": k},
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()

            incidents = [
                f"[{inc['error_type']}] Root cause: {inc['root_cause']} | "
                f"Fix: {inc['fix']} (similarity={inc['similarity']:.2f})"
                for inc in data.get("incidents", [])
                if inc.get("similarity", 0) >= RAG_SIMILARITY_THRESHOLD
            ]

            runbooks = [
                (
                    f"From: {rb['source_file']}"
                    + (f" > {rb['section_title']}" if rb.get("section_title") else "")
                    + f"\n{rb['chunk_text']}"
                )
                for rb in data.get("runbook_sections", [])
                if rb.get("similarity", 0) >= RAG_SIMILARITY_THRESHOLD
            ]

            return incidents, runbooks

    except Exception as e:
        print(f"[worker] Retrieve call failed: {e}")
    return [], []


def analyze_with_ai(
    message: str,
    pipeline_context:  str | None = None,
    similar_incidents: list[str] | None = None,
    runbook_sections:  list[str] | None = None,
) -> dict:
    """
    Call the AI Debugging Engine with full dual-source RAG context.
    Returns fallback dict on failure.
    """
    try:
        response = requests.post(
            f"{AI_ENGINE_URL}/analyze",
            json={
                "error_message":     message,
                "pipeline_context":  pipeline_context,
                "similar_incidents": similar_incidents or [],
                "runbook_sections":  runbook_sections  or [],
            },
            timeout=120,
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"[worker] AI analysis failed: {e}")
    return {
        "root_cause":    "Analysis Failed (AI Service Unavailable)",
        "suggested_fix": "Check logs manually.",
    }


# ── Core event processing ──────────────────────────────────────────────────────

def process_event(event_id: str, fields: dict):
    """
    Full RAG pipeline for one error event:
      parse → embed → retrieve similar → analyse (with RAG) → upsert → alert
    """
    job_id       = fields.get("job_id",       "unknown")
    workspace_id = fields.get("workspace_id", "default")
    raw_message  = fields.get("message",      "")

    # ── 0. Scrub PII and secrets before any storage or AI call ────────────────
    sr = scrub(raw_message)
    message = sr.text
    if sr.was_redacted:
        print(f"[worker] Scrubbed PII/secrets — categories: {sr.redactions}")

    # Cap stored log at 10 000 chars to prevent very large payloads from
    # bloating the DB. Always the scrubbed text — never the pre-scrub original.
    _RAW_LOG_MAX = 10_000
    raw_log = message[:_RAW_LOG_MAX] if message else None

    print(f"[worker] Processing {event_id} — pipeline={job_id} workspace={workspace_id}")

    # ── 1. Parse structured fields from the raw log line ──────────────────────
    parsed           = extract_error(message)
    error_type       = parsed.signature
    pipeline_context = f"Severity: {parsed.severity}\nError summary: {parsed.summary}"

    print(f"[worker] Parsed — error_type='{error_type}' severity='{parsed.severity}'")

    # ── 2. Embed the error message ─────────────────────────────────────────────
    embedding = embed_error(message)
    if embedding:
        print(f"[worker] Embedded — dim={len(embedding)}")
    else:
        print(f"[worker] Embedding unavailable — RAG will be skipped")

    # ── 3. Retrieve similar past incidents (only if embedding succeeded) ───────
    similar_incidents: list[str] = []
    if embedding:
        similar_incidents = retrieve_similar(embedding, workspace_id)
        if similar_incidents:
            print(f"[worker] Retrieved {len(similar_incidents)} similar incident(s) above threshold")
        else:
            print(f"[worker] No similar incidents found — using standard prompt")

    # ── 4. AI analysis (RAG-augmented when context available) ─────────────────
    ai_result = analyze_with_ai(message, pipeline_context, similar_incidents)

    # ── 4b. Root Cause Engine — rank hypotheses, pick the best one ────────────
    hypotheses = build_hypotheses(ai_result, parsed)
    top        = select_top(hypotheses)
    if top:
        final_root_cause = top["hypothesis"]
        final_fix        = top["fix"]
        print(
            f"[worker] RCE selected '{top['source']}' hypothesis "
            f"(score={top['score']:.2f})"
        )
    else:
        # No hypothesis available — surface the raw AI result as-is
        final_root_cause = ai_result.get("root_cause",    "Pending")
        final_fix        = ai_result.get("suggested_fix", "Pending")
        print("[worker] RCE: no hypothesis candidates — using raw AI output")

    # ── 5. Upsert Error row, storing embedding for future retrieval ───────────
    db = SessionLocal()
    try:
        existing = db.query(Error).filter(
            Error.workspace_id  == workspace_id,
            Error.pipeline_name == job_id,
            Error.error_type    == error_type,
        ).first()

        now = datetime.now(timezone.utc).isoformat()

        if existing:
            existing.root_cause  = final_root_cause
            existing.fix         = final_fix
            existing.detected_at = now
            existing.raw_log     = raw_log
            if embedding:
                existing.embedding = embedding
            print(f"[worker] Updated existing error '{error_type}' for pipeline '{job_id}'")
        else:
            db.add(Error(
                workspace_id  = workspace_id,
                pipeline_name = job_id,
                error_type    = error_type,
                root_cause    = final_root_cause,
                fix           = final_fix,
                detected_at   = now,
                raw_log       = raw_log,
                embedding     = embedding,
            ))
            print(f"[worker] Inserted new error '{error_type}' for pipeline '{job_id}'")

        db.commit()
    finally:
        db.close()

    # ── 6. Multi-channel alerts ────────────────────────────────────────────────
    run_id = fields.get("run_id", "unknown")
    send_alerts(
        pipeline_name = job_id,
        run_id        = run_id,
        error_type    = error_type,
        root_cause    = final_root_cause,
        fix           = final_fix,
        severity      = parsed.severity or "ERROR",
    )


# ── Stream consumer loop ───────────────────────────────────────────────────────

def ensure_consumer_group():
    """Create the consumer group if it doesn't exist yet."""
    try:
        redis_client.xgroup_create(STREAM_NAME, GROUP_NAME, id="$", mkstream=True)
        print(f"[worker] Created consumer group '{GROUP_NAME}' on stream '{STREAM_NAME}'")
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            print(f"[worker] Consumer group '{GROUP_NAME}' already exists — resuming")
        else:
            raise


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
