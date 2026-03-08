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

from services.shared.models import Base, Pipeline, Error

# Load api-layer main.py under a unique module name to avoid collision with
# other services' main.py files that pytest imports in the same process.
_spec = importlib.util.spec_from_file_location(
    "api_layer_main",
    os.path.join(PROJECT_ROOT, "services", "api-layer", "main.py")
)
api_layer_main = importlib.util.module_from_spec(_spec)
sys.modules["api_layer_main"] = api_layer_main
_spec.loader.exec_module(api_layer_main)

app = api_layer_main.app
get_db = api_layer_main.get_db

# In-memory SQLite — patch module-level engine/SessionLocal so startup_event
# uses the test database instead of creating pipeline_debugger.db on disk.
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

api_layer_main.engine = test_engine
api_layer_main.SessionLocal = TestingSession
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    db = TestingSession()
    db.query(Error).delete()
    db.query(Pipeline).delete()
    db.commit()
    db.close()


def seed(pipelines=None, errors=None):
    db = TestingSession()
    if pipelines:
        for p in pipelines:
            db.add(Pipeline(**p))
    if errors:
        for e in errors:
            db.add(Error(**e))
    db.commit()
    db.close()


class TestHealthEndpoint:

    def test_health_returns_200(self):
        assert client.get("/health").status_code == 200

    def test_health_returns_ok(self):
        assert client.get("/health").json() == {"status": "ok"}


class TestDashboardEndpoint:

    def test_empty_db_returns_empty_lists(self):
        response = client.get("/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["pipelines"] == []
        assert data["errors"] == []

    def test_returns_seeded_pipelines(self):
        seed(pipelines=[
            {"name": "etl-job", "status": "Failed", "last_run": "2 min ago"},
            {"name": "billing", "status": "Success", "last_run": "10 min ago"},
        ])
        pipelines = client.get("/dashboard").json()["pipelines"]
        assert len(pipelines) == 2

    def test_pipeline_has_correct_fields(self):
        seed(pipelines=[{"name": "my-pipeline", "status": "Failed", "last_run": "5 min ago"}])
        pipelines = client.get("/dashboard").json()["pipelines"]
        p = pipelines[0]
        assert p["name"] == "my-pipeline"
        assert p["status"] == "Failed"
        assert p["lastRun"] == "5 min ago"

    def test_returns_seeded_errors(self):
        seed(
            pipelines=[{"name": "etl-job", "status": "Failed", "last_run": "now"}],
            errors=[{"pipeline_name": "etl-job", "error_type": "OOM",
                     "root_cause": "memory exceeded", "fix": "increase memory"}]
        )
        errors = client.get("/dashboard").json()["errors"]
        assert len(errors) == 1

    def test_error_has_correct_fields(self):
        seed(
            pipelines=[{"name": "etl-job", "status": "Failed", "last_run": "now"}],
            errors=[{"pipeline_name": "etl-job", "error_type": "OOM",
                     "root_cause": "memory exceeded", "fix": "increase memory"}]
        )
        error = client.get("/dashboard").json()["errors"][0]
        assert error["pipeline"] == "etl-job"
        assert error["error"] == "OOM"
        assert error["rootCause"] == "memory exceeded"
        assert error["fix"] == "increase memory"


class TestCreatePipelineEndpoint:

    def test_create_pipeline_returns_200(self):
        response = client.post("/pipelines", json={
            "name": "new-pipeline",
            "status": "Success",
            "last_run": "just now"
        })
        assert response.status_code == 200

    def test_create_pipeline_returns_pipeline_data(self):
        response = client.post("/pipelines", json={
            "name": "new-pipeline",
            "status": "Success",
            "last_run": "just now"
        })
        data = response.json()
        assert data["name"] == "new-pipeline"
        assert data["status"] == "Success"
        assert data["lastRun"] == "just now"

    def test_created_pipeline_appears_in_dashboard(self):
        client.post("/pipelines", json={
            "name": "dash-pipeline",
            "status": "Failed",
            "last_run": "1 min ago"
        })
        names = [p["name"] for p in client.get("/dashboard").json()["pipelines"]]
        assert "dash-pipeline" in names

    def test_missing_name_returns_422(self):
        response = client.post("/pipelines", json={"status": "Success", "last_run": "now"})
        assert response.status_code == 422

    def test_multiple_pipelines_all_returned(self):
        for i in range(3):
            client.post("/pipelines", json={
                "name": f"pipeline-{i}",
                "status": "Success",
                "last_run": "now"
            })
        assert len(client.get("/dashboard").json()["pipelines"]) == 3


class TestPipelineErrorsEndpoint:

    def test_unknown_pipeline_returns_404(self):
        response = client.get("/pipelines/nonexistent/errors")
        assert response.status_code == 404

    def test_pipeline_with_no_errors_returns_empty_list(self):
        seed(pipelines=[{"name": "healthy-job", "status": "Success", "last_run": "now"}])
        response = client.get("/pipelines/healthy-job/errors")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_errors_for_pipeline(self):
        seed(
            pipelines=[{"name": "etl-job", "status": "Failed", "last_run": "now"}],
            errors=[
                {"pipeline_name": "etl-job", "error_type": "OOM",
                 "root_cause": "memory exceeded", "fix": "increase memory"},
                {"pipeline_name": "etl-job", "error_type": "Timeout",
                 "root_cause": "query too slow", "fix": "add index"},
            ]
        )
        errors = client.get("/pipelines/etl-job/errors").json()
        assert len(errors) == 2

    def test_error_fields_are_correct(self):
        seed(
            pipelines=[{"name": "etl-job", "status": "Failed", "last_run": "now"}],
            errors=[{"pipeline_name": "etl-job", "error_type": "OOM",
                     "root_cause": "memory exceeded", "fix": "increase memory"}]
        )
        error = client.get("/pipelines/etl-job/errors").json()[0]
        assert error["pipeline"] == "etl-job"
        assert error["error"] == "OOM"
        assert error["rootCause"] == "memory exceeded"
        assert error["fix"] == "increase memory"

    def test_only_returns_errors_for_requested_pipeline(self):
        seed(
            pipelines=[
                {"name": "etl-job", "status": "Failed", "last_run": "now"},
                {"name": "other-job", "status": "Failed", "last_run": "now"},
            ],
            errors=[
                {"pipeline_name": "etl-job", "error_type": "OOM",
                 "root_cause": "memory", "fix": "increase memory"},
                {"pipeline_name": "other-job", "error_type": "Timeout",
                 "root_cause": "slow query", "fix": "add index"},
            ]
        )
        errors = client.get("/pipelines/etl-job/errors").json()
        assert len(errors) == 1
        assert errors[0]["pipeline"] == "etl-job"
