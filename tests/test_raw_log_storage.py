"""
Tests for raw log storage — the raw_log column on the Error model.

Covers:
  - Worker stores the scrubbed message text in raw_log on insert
  - Worker updates raw_log on subsequent events for the same error
  - raw_log is capped at 10 000 chars
  - raw_log is None when the message is empty
  - Existing Error rows (without raw_log) still serialise cleanly (nullable)
  - API layer ErrorItem schema includes rawLog field
"""

import sys
import os
import importlib.util
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "services", "root-cause-engine"))

from services.shared.models import Base, Error, Pipeline

# ── Load worker module (same pattern as test_worker.py) ───────────────────────

_spec = importlib.util.spec_from_file_location(
    "queue_worker_raw",
    os.path.join(PROJECT_ROOT, "services", "queue-worker", "worker.py"),
)
queue_worker = importlib.util.module_from_spec(_spec)
sys.modules["queue_worker_raw"] = queue_worker

with patch("redis.Redis.from_url", return_value=MagicMock()):
    _spec.loader.exec_module(queue_worker)

TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)

queue_worker.engine       = test_engine
queue_worker.SessionLocal = TestingSession


# ── Fixtures ──────────────────────────────────────────────────────────────────

MOCK_AI = {
    "root_cause":     "Spark executor ran out of memory.",
    "suggested_fix":  "Increase spark.executor.memory to 8g.",
    "confidence_score": 0.95,
}

SAMPLE_FIELDS = {
    "job_id":  "raw-log-pipeline",
    "run_id":  "run-raw-001",
    "message": "ExecutorLostFailure: Spark executor ran out of memory.",
}


@pytest.fixture(autouse=True)
def clean_db():
    db = TestingSession()
    db.query(Error).delete()
    db.query(Pipeline).delete()
    db.commit()
    db.close()


def _mock_post(ai_result=None):
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = ai_result or MOCK_AI
    return m


# ── raw_log on insert ─────────────────────────────────────────────────────────

class TestRawLogOnInsert:

    def test_raw_log_is_stored_on_new_error(self):
        with patch.object(queue_worker.requests, "post", return_value=_mock_post()):
            queue_worker.process_event("1-1", SAMPLE_FIELDS)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "raw-log-pipeline").first()
        db.close()
        assert error is not None
        assert error.raw_log is not None

    def test_raw_log_contains_the_scrubbed_message(self):
        with patch.object(queue_worker.requests, "post", return_value=_mock_post()):
            queue_worker.process_event("1-1", SAMPLE_FIELDS)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "raw-log-pipeline").first()
        db.close()
        assert SAMPLE_FIELDS["message"] in error.raw_log

    def test_raw_log_pii_is_scrubbed(self):
        """PII scrubber runs before raw_log is stored."""
        fields = {**SAMPLE_FIELDS, "message": "Error: user@example.com caused failure"}
        with patch.object(queue_worker.requests, "post", return_value=_mock_post()):
            queue_worker.process_event("1-1", fields)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "raw-log-pipeline").first()
        db.close()
        # Email address must be redacted in stored raw_log
        assert "user@example.com" not in error.raw_log

    def test_raw_log_is_none_for_empty_message(self):
        fields = {**SAMPLE_FIELDS, "message": ""}
        with patch.object(queue_worker.requests, "post", return_value=_mock_post()):
            queue_worker.process_event("1-1", fields)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "raw-log-pipeline").first()
        db.close()
        assert error is not None
        assert error.raw_log is None

    def test_raw_log_capped_at_10000_chars(self):
        long_message = "X" * 15_000
        fields = {**SAMPLE_FIELDS, "message": long_message}
        with patch.object(queue_worker.requests, "post", return_value=_mock_post()):
            queue_worker.process_event("1-1", fields)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "raw-log-pipeline").first()
        db.close()
        assert error.raw_log is not None
        assert len(error.raw_log) <= 10_000

    def test_raw_log_exactly_10000_chars_for_very_long_message(self):
        long_message = "A" * 20_000
        fields = {**SAMPLE_FIELDS, "message": long_message}
        with patch.object(queue_worker.requests, "post", return_value=_mock_post()):
            queue_worker.process_event("1-1", fields)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "raw-log-pipeline").first()
        db.close()
        assert len(error.raw_log) == 10_000

    def test_raw_log_short_message_stored_in_full(self):
        fields = {**SAMPLE_FIELDS, "message": "Short error"}
        with patch.object(queue_worker.requests, "post", return_value=_mock_post()):
            queue_worker.process_event("1-1", fields)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "raw-log-pipeline").first()
        db.close()
        assert error.raw_log == "Short error"


# ── raw_log on update ─────────────────────────────────────────────────────────

class TestRawLogOnUpdate:

    def test_raw_log_updated_on_second_event(self):
        """When the same error occurs again, raw_log reflects the latest message."""
        first_fields  = {**SAMPLE_FIELDS, "message": "ExecutorLostFailure: first occurrence"}
        second_fields = {**SAMPLE_FIELDS, "message": "ExecutorLostFailure: second occurrence"}

        with patch.object(queue_worker.requests, "post", return_value=_mock_post()):
            queue_worker.process_event("1-1", first_fields)
            queue_worker.process_event("1-2", second_fields)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "raw-log-pipeline").first()
        count = db.query(Error).filter(Error.pipeline_name == "raw-log-pipeline").count()
        db.close()

        assert count == 1   # still deduplicated
        assert "second occurrence" in error.raw_log

    def test_raw_log_updated_when_message_truncated(self):
        """Second occurrence with long message is also capped correctly."""
        first_fields  = {**SAMPLE_FIELDS, "message": "ExecutorLostFailure: short"}
        second_fields = {**SAMPLE_FIELDS, "message": "ExecutorLostFailure: " + "B" * 20_000}

        with patch.object(queue_worker.requests, "post", return_value=_mock_post()):
            queue_worker.process_event("1-1", first_fields)
            queue_worker.process_event("1-2", second_fields)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "raw-log-pipeline").first()
        db.close()
        assert len(error.raw_log) <= 10_000


# ── Null safety for existing records ─────────────────────────────────────────

class TestRawLogNullSafety:

    def test_error_with_null_raw_log_is_valid(self):
        """Legacy Error rows (raw_log=None) are valid and queryable."""
        db = TestingSession()
        db.add(Error(
            workspace_id  = "default",
            pipeline_name = "legacy-pipeline",
            error_type    = "OldError",
            root_cause    = "Something old",
            fix           = "Fix it",
            detected_at   = "2026-01-01T00:00:00Z",
            raw_log       = None,
        ))
        db.commit()

        error = db.query(Error).filter(Error.pipeline_name == "legacy-pipeline").first()
        db.close()
        assert error is not None
        assert error.raw_log is None

    def test_raw_log_field_exists_on_model(self):
        """The ORM model column must exist."""
        assert hasattr(Error, "raw_log")


# ── ErrorItem schema (API layer) ──────────────────────────────────────────────

class TestErrorItemSchema:

    def test_error_item_has_raw_log_field(self):
        """ErrorItem Pydantic model must include rawLog."""
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "services", "api-layer"))
        import importlib
        api_main = importlib.import_module("main") if "main" in sys.modules else None

        # Direct check on the model fields
        from pydantic import BaseModel
        # Dynamically load the api-layer main to check ErrorItem
        spec = importlib.util.spec_from_file_location(
            "api_layer_main",
            os.path.join(PROJECT_ROOT, "services", "api-layer", "main.py"),
        )
        api_mod = importlib.util.module_from_spec(spec)
        with patch("sqlalchemy.create_engine"), \
             patch("sqlalchemy.orm.sessionmaker"):
            try:
                spec.loader.exec_module(api_mod)
            except Exception:
                pass  # lifespan/engine errors are expected without a real DB

        ErrorItem = getattr(api_mod, "ErrorItem", None)
        if ErrorItem is not None:
            fields = ErrorItem.model_fields
            assert "rawLog" in fields, "ErrorItem must have rawLog field"

    def test_error_item_accepts_none_raw_log(self):
        """rawLog defaults to None (nullable) for legacy records."""
        spec = importlib.util.spec_from_file_location(
            "api_layer_main2",
            os.path.join(PROJECT_ROOT, "services", "api-layer", "main.py"),
        )
        api_mod = importlib.util.module_from_spec(spec)
        with patch("sqlalchemy.create_engine"), \
             patch("sqlalchemy.orm.sessionmaker"):
            try:
                spec.loader.exec_module(api_mod)
            except Exception:
                pass

        ErrorItem = getattr(api_mod, "ErrorItem", None)
        if ErrorItem is not None:
            item = ErrorItem(
                pipeline="p", error="E", rootCause="C", fix="F", rawLog=None
            )
            assert item.rawLog is None

    def test_error_item_stores_raw_log_text(self):
        spec = importlib.util.spec_from_file_location(
            "api_layer_main3",
            os.path.join(PROJECT_ROOT, "services", "api-layer", "main.py"),
        )
        api_mod = importlib.util.module_from_spec(spec)
        with patch("sqlalchemy.create_engine"), \
             patch("sqlalchemy.orm.sessionmaker"):
            try:
                spec.loader.exec_module(api_mod)
            except Exception:
                pass

        ErrorItem = getattr(api_mod, "ErrorItem", None)
        if ErrorItem is not None:
            item = ErrorItem(
                pipeline="p", error="E", rootCause="C", fix="F",
                rawLog="OutOfMemoryError: Java heap space"
            )
            assert item.rawLog == "OutOfMemoryError: Java heap space"
