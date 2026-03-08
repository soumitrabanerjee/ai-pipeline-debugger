import sys
import os
import importlib.util
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from services.shared.models import Base, Pipeline, PipelineRun, Error

# Load ingestion app/main.py under a unique module name.
_spec = importlib.util.spec_from_file_location(
    "ingestion_main",
    os.path.join(PROJECT_ROOT, "services", "log-ingestion-api", "app", "main.py")
)
ingestion_main = importlib.util.module_from_spec(_spec)
sys.modules["ingestion_main"] = ingestion_main

# Patch Redis before the module executes so it never tries to connect
with patch("redis.Redis.from_url", return_value=MagicMock()):
    _spec.loader.exec_module(ingestion_main)

app = ingestion_main.app
get_db = ingestion_main.get_db

# In-memory SQLite for tests
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
ingestion_main.engine = test_engine
ingestion_main.SessionLocal = TestingSession
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

SAMPLE_ERROR_EVENT = {
    "source": "spark",
    "workspace_id": "data-team",
    "job_id": "test-spark-etl",
    "run_id": "run-001",
    "level": "ERROR",
    "timestamp": "2026-03-08T10:00:00Z",
    "message": "ExecutorLostFailure: Spark executor ran out of memory.",
}

SAMPLE_INFO_EVENT = {
    **SAMPLE_ERROR_EVENT,
    "level": "INFO",
    "run_id": "run-002",
    "message": "Job completed successfully.",
}


@pytest.fixture(autouse=True)
def clean_db():
    db = TestingSession()
    db.query(Error).delete()
    db.query(PipelineRun).delete()
    db.query(Pipeline).delete()
    db.commit()
    db.close()


@pytest.fixture(autouse=True)
def reset_redis_mock():
    """Reset the redis_client mock before each test."""
    ingestion_main.redis_client.reset_mock()


class TestHealthEndpoint:

    def test_health_returns_200(self):
        assert client.get("/health").status_code == 200

    def test_health_returns_ok(self):
        assert client.get("/health").json() == {"status": "ok"}


class TestIngestEndpoint:

    def test_error_event_returns_202(self):
        response = client.post("/ingest", json=SAMPLE_ERROR_EVENT)
        assert response.status_code == 202

    def test_info_event_returns_202(self):
        response = client.post("/ingest", json=SAMPLE_INFO_EVENT)
        assert response.status_code == 202

    def test_returns_run_id(self):
        response = client.post("/ingest", json=SAMPLE_ERROR_EVENT)
        assert response.json()["run_id"] == SAMPLE_ERROR_EVENT["run_id"]

    def test_returns_accepted_status(self):
        response = client.post("/ingest", json=SAMPLE_ERROR_EVENT)
        assert response.json()["status"] == "accepted"

    def test_missing_required_fields_returns_422(self):
        response = client.post("/ingest", json={"source": "spark"})
        assert response.status_code == 422

    def test_error_event_creates_pipeline_as_failed(self):
        client.post("/ingest", json=SAMPLE_ERROR_EVENT)
        db = TestingSession()
        pipeline = db.query(Pipeline).filter(Pipeline.name == SAMPLE_ERROR_EVENT["job_id"]).first()
        db.close()
        assert pipeline is not None
        assert pipeline.status == "Failed"

    def test_info_event_creates_pipeline_as_success(self):
        client.post("/ingest", json=SAMPLE_INFO_EVENT)
        db = TestingSession()
        pipeline = db.query(Pipeline).filter(Pipeline.name == SAMPLE_INFO_EVENT["job_id"]).first()
        db.close()
        assert pipeline is not None
        assert pipeline.status == "Success"

    def test_second_ingest_updates_pipeline_not_duplicates(self):
        client.post("/ingest", json=SAMPLE_ERROR_EVENT)
        client.post("/ingest", json=SAMPLE_INFO_EVENT)
        db = TestingSession()
        count = db.query(Pipeline).filter(Pipeline.name == SAMPLE_ERROR_EVENT["job_id"]).count()
        pipeline = db.query(Pipeline).filter(Pipeline.name == SAMPLE_ERROR_EVENT["job_id"]).first()
        db.close()
        assert count == 1
        assert pipeline.status == "Success"

    def test_error_event_publishes_to_redis_stream(self):
        client.post("/ingest", json=SAMPLE_ERROR_EVENT)
        ingestion_main.redis_client.xadd.assert_called_once()
        call_args = ingestion_main.redis_client.xadd.call_args
        stream, fields = call_args[0]
        assert stream == "log_events"
        assert fields["job_id"] == SAMPLE_ERROR_EVENT["job_id"]
        assert fields["message"] == SAMPLE_ERROR_EVENT["message"]
        assert fields["run_id"] == SAMPLE_ERROR_EVENT["run_id"]

    def test_info_event_does_not_publish_to_redis(self):
        client.post("/ingest", json=SAMPLE_INFO_EVENT)
        ingestion_main.redis_client.xadd.assert_not_called()

    def test_error_event_does_not_create_error_record_synchronously(self):
        """Error records are now created by the async worker, not the ingestion API."""
        client.post("/ingest", json=SAMPLE_ERROR_EVENT)
        db = TestingSession()
        error = db.query(Error).filter(Error.pipeline_name == SAMPLE_ERROR_EVENT["job_id"]).first()
        db.close()
        assert error is None


class TestPipelineRunTracking:

    def test_error_event_creates_pipeline_run(self):
        client.post("/ingest", json=SAMPLE_ERROR_EVENT)
        db = TestingSession()
        run = db.query(PipelineRun).filter(PipelineRun.run_id == SAMPLE_ERROR_EVENT["run_id"]).first()
        db.close()
        assert run is not None

    def test_pipeline_run_has_correct_run_id(self):
        client.post("/ingest", json=SAMPLE_ERROR_EVENT)
        db = TestingSession()
        run = db.query(PipelineRun).filter(PipelineRun.run_id == SAMPLE_ERROR_EVENT["run_id"]).first()
        db.close()
        assert run.run_id == SAMPLE_ERROR_EVENT["run_id"]

    def test_failed_event_creates_run_with_failed_status(self):
        client.post("/ingest", json=SAMPLE_ERROR_EVENT)
        db = TestingSession()
        run = db.query(PipelineRun).filter(PipelineRun.run_id == SAMPLE_ERROR_EVENT["run_id"]).first()
        db.close()
        assert run.status == "Failed"

    def test_success_event_creates_run_with_success_status(self):
        client.post("/ingest", json=SAMPLE_INFO_EVENT)
        db = TestingSession()
        run = db.query(PipelineRun).filter(PipelineRun.run_id == SAMPLE_INFO_EVENT["run_id"]).first()
        db.close()
        assert run.status == "Success"

    def test_duplicate_run_id_does_not_create_second_row(self):
        client.post("/ingest", json=SAMPLE_ERROR_EVENT)
        client.post("/ingest", json=SAMPLE_ERROR_EVENT)  # same run_id
        db = TestingSession()
        count = db.query(PipelineRun).filter(PipelineRun.run_id == SAMPLE_ERROR_EVENT["run_id"]).count()
        db.close()
        assert count == 1

    def test_two_different_run_ids_create_two_rows(self):
        event_a = {**SAMPLE_ERROR_EVENT, "run_id": "run-A"}
        event_b = {**SAMPLE_ERROR_EVENT, "run_id": "run-B"}
        client.post("/ingest", json=event_a)
        client.post("/ingest", json=event_b)
        db = TestingSession()
        count = db.query(PipelineRun).filter(
            PipelineRun.pipeline_name == SAMPLE_ERROR_EVENT["job_id"]
        ).count()
        db.close()
        assert count == 2

    def test_pipeline_run_stores_timestamp(self):
        client.post("/ingest", json=SAMPLE_ERROR_EVENT)
        db = TestingSession()
        run = db.query(PipelineRun).filter(PipelineRun.run_id == SAMPLE_ERROR_EVENT["run_id"]).first()
        db.close()
        assert run.created_at == SAMPLE_ERROR_EVENT["timestamp"]
