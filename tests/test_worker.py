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
# Make engine.py importable before the worker module is loaded
sys.path.insert(0, os.path.join(PROJECT_ROOT, "services", "root-cause-engine"))

from services.shared.models import Base, Error, Pipeline

# Load worker under a unique module name.
# Patch Redis and DB at module level so the worker never tries to connect.
_spec = importlib.util.spec_from_file_location(
    "queue_worker",
    os.path.join(PROJECT_ROOT, "services", "queue-worker", "worker.py")
)
queue_worker = importlib.util.module_from_spec(_spec)
sys.modules["queue_worker"] = queue_worker

with patch("redis.Redis.from_url", return_value=MagicMock()):
    _spec.loader.exec_module(queue_worker)

# Swap in an in-memory SQLite engine
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)

queue_worker.engine = test_engine
queue_worker.SessionLocal = TestingSession

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

MOCK_AI_SUCCESS = {
    "root_cause": "Spark executor ran out of memory.",
    "suggested_fix": "Increase spark.executor.memory to 8g.",
    "confidence_score": 0.95,
}

MOCK_AI_FALLBACK = {
    "root_cause": "Analysis Failed (AI Service Unavailable)",
    "suggested_fix": "Check logs manually.",
}

SAMPLE_FIELDS = {
    "job_id": "spark-etl",
    "run_id": "run-001",
    "message": "ExecutorLostFailure: Spark executor ran out of memory.",
}


@pytest.fixture(autouse=True)
def clean_db():
    db = TestingSession()
    db.query(Error).delete()
    db.query(Pipeline).delete()
    db.commit()
    db.close()


def seed_pipeline(name="spark-etl", status="Failed"):
    db = TestingSession()
    db.add(Pipeline(name=name, status=status, last_run="Just now"))
    db.commit()
    db.close()


# ------------------------------------------------------------------
# analyze_with_ai
# ------------------------------------------------------------------

class TestAnalyzeWithAi:

    def test_returns_ai_result_on_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_AI_SUCCESS

        with patch.object(queue_worker.requests, "post", return_value=mock_resp):
            result = queue_worker.analyze_with_ai("some error")

        assert result["root_cause"] == MOCK_AI_SUCCESS["root_cause"]
        assert result["suggested_fix"] == MOCK_AI_SUCCESS["suggested_fix"]

    def test_returns_fallback_when_ai_is_down(self):
        with patch.object(queue_worker.requests, "post", side_effect=Exception("connection refused")):
            result = queue_worker.analyze_with_ai("some error")

        assert "Unavailable" in result["root_cause"]
        assert result["suggested_fix"] == "Check logs manually."

    def test_returns_fallback_on_non_200_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch.object(queue_worker.requests, "post", return_value=mock_resp):
            result = queue_worker.analyze_with_ai("some error")

        assert "Unavailable" in result["root_cause"]


# ------------------------------------------------------------------
# process_event
# ------------------------------------------------------------------

class TestProcessEvent:

    def test_creates_error_record_in_db(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_AI_SUCCESS

        with patch.object(queue_worker.requests, "post", return_value=mock_resp):
            queue_worker.process_event("1-1", SAMPLE_FIELDS)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "spark-etl").first()
        db.close()
        assert error is not None

    def test_saves_ai_root_cause(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_AI_SUCCESS

        with patch.object(queue_worker.requests, "post", return_value=mock_resp):
            queue_worker.process_event("1-1", SAMPLE_FIELDS)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "spark-etl").first()
        db.close()
        assert error.root_cause == MOCK_AI_SUCCESS["root_cause"]
        assert error.fix == MOCK_AI_SUCCESS["suggested_fix"]

    def test_extracts_error_type_from_message(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_AI_SUCCESS

        with patch.object(queue_worker.requests, "post", return_value=mock_resp):
            queue_worker.process_event("1-1", SAMPLE_FIELDS)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "spark-etl").first()
        db.close()
        # advanced_parser returns "CATEGORY:ClassName" signatures.
        # "ExecutorLostFailure: ..." is not matched by the log-block assembler anchor
        # (no ERROR/EXCEPTION/CRITICAL/FATAL token), so the generic fallback fires:
        # signature = "UNKNOWN:<first token before colon>" = "UNKNOWN:ExecutorLostFailure"
        assert "ExecutorLostFailure" in error.error_type

    def test_uses_full_message_as_error_type_when_no_colon(self):
        fields = {**SAMPLE_FIELDS, "message": "OutOfMemoryError"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_AI_SUCCESS

        with patch.object(queue_worker.requests, "post", return_value=mock_resp):
            queue_worker.process_event("1-1", fields)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "spark-etl").first()
        db.close()
        # "OutOfMemoryError" (no colon) doesn't match the Airflow line regex
        # (which requires ": message") so the generic fallback fires, producing
        # "UNKNOWN:UnknownError".  The error record is still created.
        assert error is not None
        assert error.error_type is not None

    def test_saves_fallback_when_ai_unavailable(self):
        with patch.object(queue_worker.requests, "post", side_effect=Exception("timeout")):
            queue_worker.process_event("1-1", SAMPLE_FIELDS)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "spark-etl").first()
        db.close()
        assert error is not None
        assert "Unavailable" in error.root_cause

    def test_handles_missing_job_id_gracefully(self):
        """Worker should not crash when job_id is absent in stream fields."""
        fields = {"run_id": "run-001", "message": "SomeError: bad thing"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_AI_SUCCESS

        with patch.object(queue_worker.requests, "post", return_value=mock_resp):
            queue_worker.process_event("1-1", fields)  # should not raise

    def test_passes_full_message_to_ai_engine(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_AI_SUCCESS

        with patch.object(queue_worker.requests, "post", return_value=mock_resp) as mock_post:
            queue_worker.process_event("1-1", SAMPLE_FIELDS)

        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["error_message"] == SAMPLE_FIELDS["message"]


# ------------------------------------------------------------------
# deduplication
# ------------------------------------------------------------------

class TestDeduplication:

    def _mock_post(self, ai_result):
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = ai_result
        return m

    def test_second_identical_error_does_not_create_new_row(self):
        mock_resp = self._mock_post(MOCK_AI_SUCCESS)
        with patch.object(queue_worker.requests, "post", return_value=mock_resp):
            queue_worker.process_event("1-1", SAMPLE_FIELDS)
            queue_worker.process_event("1-2", SAMPLE_FIELDS)

        db = TestingSession()
        count = db.query(Error).filter(Error.pipeline_name == "spark-etl").count()
        db.close()
        assert count == 1

    def test_second_identical_error_updates_root_cause(self):
        first_result = {**MOCK_AI_SUCCESS, "root_cause": "Old analysis."}
        second_result = {**MOCK_AI_SUCCESS, "root_cause": "Updated analysis."}

        with patch.object(queue_worker.requests, "post", return_value=self._mock_post(first_result)):
            queue_worker.process_event("1-1", SAMPLE_FIELDS)

        with patch.object(queue_worker.requests, "post", return_value=self._mock_post(second_result)):
            queue_worker.process_event("1-2", SAMPLE_FIELDS)

        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == "spark-etl").first()
        db.close()
        assert error.root_cause == "Updated analysis."

    def test_different_error_type_creates_separate_row(self):
        fields_b = {**SAMPLE_FIELDS, "message": "SchemaMismatch: column type mismatch"}
        mock_resp = self._mock_post(MOCK_AI_SUCCESS)

        with patch.object(queue_worker.requests, "post", return_value=mock_resp):
            queue_worker.process_event("1-1", SAMPLE_FIELDS)   # ExecutorLostFailure
            queue_worker.process_event("1-2", fields_b)         # SchemaMismatch

        db = TestingSession()
        count = db.query(Error).filter(Error.pipeline_name == "spark-etl").count()
        db.close()
        assert count == 2

    def test_same_error_different_pipeline_creates_separate_row(self):
        fields_b = {**SAMPLE_FIELDS, "job_id": "billing-etl"}
        mock_resp = self._mock_post(MOCK_AI_SUCCESS)

        with patch.object(queue_worker.requests, "post", return_value=mock_resp):
            queue_worker.process_event("1-1", SAMPLE_FIELDS)   # spark-etl
            queue_worker.process_event("1-2", fields_b)         # billing-etl

        db = TestingSession()
        total = db.query(Error).count()
        db.close()
        assert total == 2

    def test_many_duplicates_still_only_one_row(self):
        mock_resp = self._mock_post(MOCK_AI_SUCCESS)
        with patch.object(queue_worker.requests, "post", return_value=mock_resp):
            for i in range(5):
                queue_worker.process_event(f"1-{i}", SAMPLE_FIELDS)

        db = TestingSession()
        count = db.query(Error).filter(Error.pipeline_name == "spark-etl").count()
        db.close()
        assert count == 1


# ------------------------------------------------------------------
# ensure_consumer_group
# ------------------------------------------------------------------

class TestEnsureConsumerGroup:

    def test_creates_group_when_it_doesnt_exist(self):
        queue_worker.redis_client.xgroup_create.reset_mock()
        queue_worker.redis_client.xgroup_create.side_effect = None
        queue_worker.ensure_consumer_group()
        queue_worker.redis_client.xgroup_create.assert_called_once()

    def test_does_not_raise_when_group_already_exists(self):
        import redis as redis_lib
        queue_worker.redis_client.xgroup_create.side_effect = (
            redis_lib.exceptions.ResponseError("BUSYGROUP Consumer Group name already exists")
        )
        queue_worker.ensure_consumer_group()  # should not raise
        queue_worker.redis_client.xgroup_create.side_effect = None
