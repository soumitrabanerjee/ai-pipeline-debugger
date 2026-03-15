"""
Tests for Feature #4 — Per-workspace API keys + PostgreSQL RLS.

Coverage:
  - API key generation format and uniqueness
  - CRUD: create, list, revoke
  - Auth: valid key accepted, invalid key rejected, revoked key rejected
  - Duplicate name rejection
  - Webhook routing: API key overrides workspace_id
  - Workspace isolation: one workspace cannot see another's data via API key
  - RLS helper: _set_rls_workspace is a no-op on non-PostgreSQL backends
"""

import sys
import os
import importlib.util
import hashlib
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from services.shared.models import Base, ApiKey, User, Pipeline, Error

# ── Load api-layer app ─────────────────────────────────────────────────────────

_spec = importlib.util.spec_from_file_location(
    "api_layer_main_keys",
    os.path.join(PROJECT_ROOT, "services", "api-layer", "main.py"),
)
api_layer_main = importlib.util.module_from_spec(_spec)
sys.modules["api_layer_main_keys"] = api_layer_main
_spec.loader.exec_module(api_layer_main)

app     = api_layer_main.app
get_db  = api_layer_main.get_db

# ── Load ingestion-api app ─────────────────────────────────────────────────────

_ingest_spec = importlib.util.spec_from_file_location(
    "ingest_main_keys",
    os.path.join(PROJECT_ROOT, "services", "log-ingestion-api", "app", "main.py"),
)
ingest_main = importlib.util.module_from_spec(_ingest_spec)
sys.modules["ingest_main_keys"] = ingest_main
_ingest_spec.loader.exec_module(ingest_main)

ingest_app    = ingest_main.app
ingest_get_db = ingest_main.get_db

# ── Shared in-memory SQLite ────────────────────────────────────────────────────

TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)

# Patch both apps to use the same in-memory DB
api_layer_main.engine       = test_engine
api_layer_main.SessionLocal = TestingSession
ingest_main.engine          = test_engine
ingest_main.SessionLocal    = TestingSession


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db]            = override_get_db
ingest_app.dependency_overrides[ingest_get_db] = override_get_db

api_client    = TestClient(app)
ingest_client = TestClient(ingest_app)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    """Wipe all rows and reset rate limiter before each test."""
    db = TestingSession()
    db.query(ApiKey).delete()
    db.query(Error).delete()
    db.query(Pipeline).delete()
    db.query(User).delete()
    db.commit()
    db.close()
    # Reset slowapi in-memory rate limit counters so each test starts clean
    try:
        api_layer_main.limiter._storage.reset()
    except Exception:
        pass


def _register(email: str = "user@example.com", password: str = "pass123") -> dict:
    """Register a user and return the auth response dict."""
    resp = api_client.post(
        "/auth/register",
        json={"email": email, "name": "Test User", "password": password},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _auth_headers(token: str) -> dict:
    return {"x-session-token": token}


def _create_key(token: str, name: str = "ci-key") -> dict:
    """Create an API key and return the ApiKeyCreated response."""
    resp = api_client.post(
        "/api-keys",
        json={"name": name},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── generate_api_key unit tests ───────────────────────────────────────────────

class TestGenerateApiKey:

    def test_key_has_dpd_prefix(self):
        key, prefix, hsh = api_layer_main.generate_api_key()
        assert key.startswith("dpd_")

    def test_key_total_length(self):
        # "dpd_" (4) + 64 hex chars = 68
        key, _, _ = api_layer_main.generate_api_key()
        assert len(key) == 68

    def test_prefix_is_first_12_chars(self):
        key, prefix, _ = api_layer_main.generate_api_key()
        assert prefix == key[:12]

    def test_hash_is_sha256_of_key(self):
        key, _, hsh = api_layer_main.generate_api_key()
        assert hsh == hashlib.sha256(key.encode()).hexdigest()

    def test_two_calls_produce_different_keys(self):
        k1, _, _ = api_layer_main.generate_api_key()
        k2, _, _ = api_layer_main.generate_api_key()
        assert k1 != k2


# ── _set_rls_workspace unit test ──────────────────────────────────────────────

class TestSetRLSWorkspace:

    def test_no_op_on_sqlite(self):
        """Should not raise on SQLite (which doesn't support SET LOCAL)."""
        db = TestingSession()
        try:
            # Must not raise
            api_layer_main._set_rls_workspace(db, "workspace-123")
        finally:
            db.close()


# ── POST /api-keys ─────────────────────────────────────────────────────────────

class TestCreateApiKey:

    def test_requires_auth(self):
        resp = api_client.post("/api-keys", json={"name": "test-key"})
        assert resp.status_code == 401

    def test_creates_key_successfully(self):
        auth = _register()
        data = _create_key(auth["token"])
        assert data["name"] == "ci-key"
        assert data["key"].startswith("dpd_")
        assert len(data["key"]) == 68
        assert data["key_prefix"] == data["key"][:12]
        assert "id" in data
        assert "created_at" in data

    def test_full_key_not_stored_in_db(self):
        auth = _register()
        created = _create_key(auth["token"])
        db = TestingSession()
        record = db.query(ApiKey).filter(ApiKey.id == created["id"]).first()
        db.close()
        assert record is not None
        assert record.key_hash != created["key"]
        assert record.key_hash == hashlib.sha256(created["key"].encode()).hexdigest()

    def test_duplicate_name_rejected(self):
        auth = _register()
        _create_key(auth["token"], name="my-key")
        resp = api_client.post(
            "/api-keys",
            json={"name": "my-key"},
            headers=_auth_headers(auth["token"]),
        )
        assert resp.status_code == 409

    def test_different_users_can_use_same_name(self):
        auth1 = _register("a@example.com")
        auth2 = _register("b@example.com")
        _create_key(auth1["token"], name="shared-name")
        # Should succeed for a different workspace
        resp = api_client.post(
            "/api-keys",
            json={"name": "shared-name"},
            headers=_auth_headers(auth2["token"]),
        )
        assert resp.status_code == 201

    def test_key_is_active_on_creation(self):
        auth = _register()
        created = _create_key(auth["token"])
        db = TestingSession()
        record = db.query(ApiKey).filter(ApiKey.id == created["id"]).first()
        db.close()
        assert record.is_active is True


# ── GET /api-keys ──────────────────────────────────────────────────────────────

class TestListApiKeys:

    def test_requires_auth(self):
        resp = api_client.get("/api-keys")
        assert resp.status_code == 401

    def test_default_key_for_new_user(self):
        auth = _register()
        resp = api_client.get("/api-keys", headers=_auth_headers(auth["token"]))
        assert resp.status_code == 200
        keys = resp.json()
        assert len(keys) == 1
        assert keys[0]["name"] == "default"

    def test_lists_created_keys(self):
        auth = _register()
        _create_key(auth["token"], "key-a")
        _create_key(auth["token"], "key-b")
        resp = api_client.get("/api-keys", headers=_auth_headers(auth["token"]))
        assert resp.status_code == 200
        names = [k["name"] for k in resp.json()]
        assert "key-a" in names
        assert "key-b" in names

    def test_full_key_never_returned_in_list(self):
        auth = _register()
        created = _create_key(auth["token"])
        resp = api_client.get("/api-keys", headers=_auth_headers(auth["token"]))
        # Find the specific key we just created (list also contains auto-created "default" key)
        keys = resp.json()
        listed = next(k for k in keys if k["id"] == created["id"])
        assert "key" not in listed                        # full key field absent
        assert listed["key_prefix"] == created["key_prefix"]
        assert len(listed["key_prefix"]) == 12

    def test_workspace_isolation_in_listing(self):
        auth1 = _register("u1@example.com")
        auth2 = _register("u2@example.com")
        _create_key(auth1["token"], "u1-key")
        _create_key(auth2["token"], "u2-key")

        keys1 = [k["name"] for k in api_client.get(
            "/api-keys", headers=_auth_headers(auth1["token"])
        ).json()]
        keys2 = [k["name"] for k in api_client.get(
            "/api-keys", headers=_auth_headers(auth2["token"])
        ).json()]

        assert "u1-key" in keys1 and "u2-key" not in keys1
        assert "u2-key" in keys2 and "u1-key" not in keys2

    def test_revoked_keys_appear_in_list_with_is_active_false(self):
        auth = _register()
        created = _create_key(auth["token"])
        api_client.delete(f"/api-keys/{created['id']}", headers=_auth_headers(auth["token"]))
        keys = api_client.get("/api-keys", headers=_auth_headers(auth["token"])).json()
        assert any(k["id"] == created["id"] and not k["is_active"] for k in keys)


# ── DELETE /api-keys/{key_id} ──────────────────────────────────────────────────

class TestRevokeApiKey:

    def test_requires_auth(self):
        resp = api_client.delete("/api-keys/1")
        assert resp.status_code == 401

    def test_revoke_existing_key(self):
        auth = _register()
        created = _create_key(auth["token"])
        resp = api_client.delete(
            f"/api-keys/{created['id']}",
            headers=_auth_headers(auth["token"]),
        )
        assert resp.status_code == 204

    def test_revoked_key_is_inactive_in_db(self):
        auth = _register()
        created = _create_key(auth["token"])
        api_client.delete(f"/api-keys/{created['id']}", headers=_auth_headers(auth["token"]))
        db = TestingSession()
        record = db.query(ApiKey).filter(ApiKey.id == created["id"]).first()
        db.close()
        assert record.is_active is False

    def test_cannot_revoke_another_workspaces_key(self):
        auth1 = _register("x@example.com")
        auth2 = _register("y@example.com")
        created = _create_key(auth1["token"])
        resp = api_client.delete(
            f"/api-keys/{created['id']}",
            headers=_auth_headers(auth2["token"]),
        )
        assert resp.status_code == 404

    def test_revoke_nonexistent_key_returns_404(self):
        auth = _register()
        resp = api_client.delete("/api-keys/99999", headers=_auth_headers(auth["token"]))
        assert resp.status_code == 404


# ── Ingestion API — x-api-key validation ──────────────────────────────────────

class TestIngestionApiKeyAuth:

    def test_webhook_without_api_key_returns_401(self):
        resp = ingest_client.post(
            "/webhook/generic",
            json={"pipeline": "test-pipe", "level": "INFO", "message": "ok"},
        )
        assert resp.status_code == 401

    def test_webhook_with_invalid_api_key_returns_401(self):
        resp = ingest_client.post(
            "/webhook/generic",
            json={"pipeline": "test-pipe", "level": "INFO", "message": "ok"},
            headers={"x-api-key": "dpd_thisisnotavalidkey00000000000000000000000000000000000000000000"},
        )
        assert resp.status_code == 401

    def test_webhook_with_revoked_key_returns_401(self):
        # Create and immediately revoke a key
        auth = _register()
        created = _create_key(auth["token"])
        api_client.delete(f"/api-keys/{created['id']}", headers=_auth_headers(auth["token"]))

        resp = ingest_client.post(
            "/webhook/generic",
            json={"pipeline": "pipe", "level": "INFO", "message": "test"},
            headers={"x-api-key": created["key"]},
        )
        assert resp.status_code == 401

    def test_webhook_with_valid_key_accepted(self):
        auth = _register()
        created = _create_key(auth["token"])
        resp = ingest_client.post(
            "/webhook/generic",
            json={"pipeline": "pipe", "level": "INFO", "message": "test"},
            headers={"x-api-key": created["key"]},
        )
        assert resp.status_code == 202

    def test_airflow_webhook_with_invalid_key_returns_401(self):
        resp = ingest_client.post(
            "/webhook/airflow",
            json={
                "dag_id": "my_dag",
                "run_id": "run_001",
                "state":  "failed",
                "exception": "some error",
            },
            headers={"x-api-key": "dpd_bad000000000000000000000000000000000000000000000000000000000000"},
        )
        assert resp.status_code == 401

    def test_ingest_endpoint_with_invalid_key_returns_401(self):
        resp = ingest_client.post(
            "/ingest",
            json={
                "source": "test", "workspace_id": "ws1", "job_id": "job",
                "run_id": "r1", "level": "INFO",
                "timestamp": "2026-01-01T00:00:00Z", "message": "hello",
            },
            headers={"x-api-key": "dpd_bad000000000000000000000000000000000000000000000000000000000000"},
        )
        assert resp.status_code == 401


# ── Workspace routing via API key ─────────────────────────────────────────────

class TestWorkspaceRoutingViaApiKey:

    def test_api_key_workspace_overrides_payload(self):
        """
        When a valid API key is provided, the workspace_id bound to the key
        should be used — ignoring any workspace_id in the payload.
        """
        auth = _register()
        created = _create_key(auth["token"])

        # The user's workspace_id is str(user.id)
        db = TestingSession()
        user = db.query(User).filter(User.email == "user@example.com").first()
        expected_ws = str(user.id)
        db.close()

        # Send with a different workspace_id in payload — key should override it
        resp = ingest_client.post(
            "/ingest",
            json={
                "source": "test", "workspace_id": "payload-ws",
                "job_id": "my-pipeline", "run_id": "run-xyz",
                "level": "INFO", "timestamp": "2026-01-01T00:00:00Z",
                "message": "test event",
            },
            headers={"x-api-key": created["key"]},
        )
        assert resp.status_code == 202

        # Pipeline should be stored under the API key's workspace, not "payload-ws"
        db = TestingSession()
        pipeline = db.query(Pipeline).filter(
            Pipeline.workspace_id == expected_ws,
            Pipeline.name == "my-pipeline",
        ).first()
        db.close()
        assert pipeline is not None, "Pipeline should be in API key workspace"

    def test_generic_webhook_routes_to_api_key_workspace(self):
        auth = _register()
        created = _create_key(auth["token"])
        db = TestingSession()
        user = db.query(User).filter(User.email == "user@example.com").first()
        expected_ws = str(user.id)
        db.close()

        resp = ingest_client.post(
            "/webhook/generic",
            json={"pipeline": "webhook-pipe", "level": "INFO", "message": "ok"},
            headers={"x-api-key": created["key"]},
        )
        assert resp.status_code == 202

        db = TestingSession()
        pipeline = db.query(Pipeline).filter(
            Pipeline.workspace_id == expected_ws,
            Pipeline.name == "webhook-pipe",
        ).first()
        db.close()
        assert pipeline is not None


# ── Workspace isolation (application-level) ───────────────────────────────────

class TestWorkspaceIsolation:
    """
    Verify that one authenticated user cannot see another user's data,
    even when both have data in the DB. This tests the application-layer
    workspace filtering that RLS mirrors at the DB level.
    """

    def test_dashboard_only_returns_own_data(self):
        auth1 = _register("alice@example.com")
        auth2 = _register("bob@example.com")

        # Seed a pipeline directly into Alice's workspace
        db = TestingSession()
        u1 = db.query(User).filter(User.email == "alice@example.com").first()
        u2 = db.query(User).filter(User.email == "bob@example.com").first()
        db.add(Pipeline(workspace_id=str(u1.id), name="alice-pipe", status="Failed", last_run="now"))
        db.add(Pipeline(workspace_id=str(u2.id), name="bob-pipe",   status="Success", last_run="now"))
        db.commit()
        db.close()

        alice_data = api_client.get("/dashboard", headers=_auth_headers(auth1["token"])).json()
        bob_data   = api_client.get("/dashboard", headers=_auth_headers(auth2["token"])).json()

        alice_names = [p["name"] for p in alice_data["pipelines"]]
        bob_names   = [p["name"] for p in bob_data["pipelines"]]

        assert "alice-pipe" in alice_names and "bob-pipe" not in alice_names
        assert "bob-pipe" in bob_names and "alice-pipe" not in bob_names

    def test_api_keys_isolated_between_users(self):
        auth1 = _register("c@example.com")
        auth2 = _register("d@example.com")
        _create_key(auth1["token"], "c-key")
        _create_key(auth2["token"], "d-key")

        keys1 = [k["name"] for k in api_client.get("/api-keys", headers=_auth_headers(auth1["token"])).json()]
        keys2 = [k["name"] for k in api_client.get("/api-keys", headers=_auth_headers(auth2["token"])).json()]
        assert "c-key" in keys1 and "d-key" not in keys1
        assert "d-key" in keys2 and "c-key" not in keys2
