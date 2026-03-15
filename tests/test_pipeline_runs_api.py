"""
Tests for the GET /pipelines/{name}/runs endpoint in the API layer.
Uses in-memory SQLite; no real PostgreSQL required.
"""

import sys
import os
import importlib.util
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from services.shared.models import Base, Pipeline, PipelineRun, Error

# Load api-layer/main.py under a unique module name
_spec = importlib.util.spec_from_file_location(
    "api_main_runs",
    os.path.join(PROJECT_ROOT, "services", "api-layer", "main.py"),
)
api_main = importlib.util.module_from_spec(_spec)
sys.modules["api_main_runs"] = api_main
_spec.loader.exec_module(api_main)

# Swap in in-memory SQLite
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
api_main.engine = test_engine
api_main.SessionLocal = TestingSession
Base.metadata.create_all(bind=test_engine)

app = api_main.app
get_db = api_main.get_db


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


class _FakeUser:
    id = "default"
    email = "test@test.com"
    name = "Test"
    paid = True
    plan = "pro"
    session_token = "test-token"
    created_at = "2026-01-01"
    is_admin = False
    password_hash = "x"

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[api_main.get_current_user] = lambda: _FakeUser()
client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    db = TestingSession()
    db.query(Error).delete()
    db.query(PipelineRun).delete()
    db.query(Pipeline).delete()
    db.commit()
    db.close()


def _seed_pipeline(name="customer_etl"):
    db = TestingSession()
    db.add(Pipeline(name=name, status="Failed", last_run="now"))
    db.commit()
    db.close()


def _seed_run(pipeline_name, run_id, status="Failed", created_at="2026-03-08T10:00:00Z"):
    db = TestingSession()
    db.add(PipelineRun(
        pipeline_name=pipeline_name,
        run_id=run_id,
        status=status,
        created_at=created_at,
    ))
    db.commit()
    db.close()


class TestGetPipelineRuns:

    def test_returns_200_for_existing_pipeline(self):
        _seed_pipeline()
        response = client.get("/pipelines/customer_etl/runs")
        assert response.status_code == 200

    def test_returns_404_for_unknown_pipeline(self):
        response = client.get("/pipelines/nonexistent/runs")
        assert response.status_code == 404

    def test_returns_empty_list_when_no_runs(self):
        _seed_pipeline()
        response = client.get("/pipelines/customer_etl/runs")
        assert response.json() == []

    def test_returns_single_run(self):
        _seed_pipeline()
        _seed_run("customer_etl", "run-001")
        response = client.get("/pipelines/customer_etl/runs")
        data = response.json()
        assert len(data) == 1
        assert data[0]["runId"] == "run-001"

    def test_run_item_has_required_fields(self):
        _seed_pipeline()
        _seed_run("customer_etl", "run-001", status="Failed", created_at="2026-03-08T10:00:00Z")
        data = client.get("/pipelines/customer_etl/runs").json()
        run = data[0]
        assert "runId" in run
        assert "status" in run
        assert "createdAt" in run

    def test_run_status_is_preserved(self):
        _seed_pipeline()
        _seed_run("customer_etl", "run-001", status="Success")
        data = client.get("/pipelines/customer_etl/runs").json()
        assert data[0]["status"] == "Success"

    def test_run_timestamp_is_preserved(self):
        _seed_pipeline()
        _seed_run("customer_etl", "run-001", created_at="2026-03-08T15:30:00Z")
        data = client.get("/pipelines/customer_etl/runs").json()
        assert data[0]["createdAt"] == "2026-03-08T15:30:00Z"

    def test_returns_multiple_runs(self):
        _seed_pipeline()
        _seed_run("customer_etl", "run-001", created_at="2026-03-08T09:00:00Z")
        _seed_run("customer_etl", "run-002", created_at="2026-03-08T10:00:00Z")
        _seed_run("customer_etl", "run-003", created_at="2026-03-08T11:00:00Z")
        data = client.get("/pipelines/customer_etl/runs").json()
        assert len(data) == 3

    def test_runs_ordered_newest_first(self):
        _seed_pipeline()
        _seed_run("customer_etl", "run-old",  created_at="2026-03-08T09:00:00Z")
        _seed_run("customer_etl", "run-new",  created_at="2026-03-08T11:00:00Z")
        _seed_run("customer_etl", "run-mid",  created_at="2026-03-08T10:00:00Z")
        data = client.get("/pipelines/customer_etl/runs").json()
        run_ids = [r["runId"] for r in data]
        assert run_ids == ["run-new", "run-mid", "run-old"]

    def test_runs_isolated_between_pipelines(self):
        _seed_pipeline("pipeline_a")
        _seed_pipeline("pipeline_b")
        _seed_run("pipeline_a", "run-a1")
        _seed_run("pipeline_b", "run-b1")
        _seed_run("pipeline_b", "run-b2")
        data_a = client.get("/pipelines/pipeline_a/runs").json()
        data_b = client.get("/pipelines/pipeline_b/runs").json()
        assert len(data_a) == 1
        assert len(data_b) == 2
