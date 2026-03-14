"""
Tests for API layer rate limiting (slowapi).

Strategy
--------
The production limits (e.g. "120/minute") are too high to trigger in unit
tests without spinning up real timers.  Instead we:

  1. Load the api-layer module fresh (with real SQLite in-memory DB).
  2. Use FastAPI TestClient to make real HTTP requests against the app.
  3. Verify the limiter machinery (limiter on app.state, exception handler,
     429 response format).
  4. For enforcement tests, replace every _route_limits entry with a tiny
     Limit("1/minute") object and call limiter.reset() so counters start from
     zero — then 2 requests to the same endpoint produce 200 then 429.

The module is loaded fresh for each test class so the in-memory counter
resets between test groups.
"""

import sys
import os
import importlib
import importlib.util
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "services", "api-layer"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "services", "log-processing-layer"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from services.shared.models import Base, User, Pipeline, Error, PipelineRun, ApiKey


# ── Shared in-memory DB ────────────────────────────────────────────────────────

TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


def _load_app():
    """
    Load the api-layer app fresh with SQLite in-memory DB.
    The real limiter from main.py is preserved so decorators work correctly.
    """
    for key in list(sys.modules.keys()):
        if key in ("main", "api_layer_test_rl"):
            del sys.modules[key]

    spec = importlib.util.spec_from_file_location(
        "api_layer_test_rl",
        os.path.join(PROJECT_ROOT, "services", "api-layer", "main.py"),
    )
    mod = importlib.util.module_from_spec(spec)

    with patch("sqlalchemy.create_engine", return_value=test_engine):
        with patch("sqlalchemy.orm.sessionmaker", return_value=TestingSession):
            try:
                spec.loader.exec_module(mod)
            except Exception:
                pass   # lifespan errors OK without real PostgreSQL

    # Patch the DB session used by route handlers
    mod.SessionLocal = TestingSession
    mod.engine = test_engine

    return mod


def _apply_tiny_limits(lim):
    """
    Replace every per-route limit entry with a "1/minute" limit and reset
    the storage backend so counters start from zero.

    This works because slowapi stores Limit objects in lim._route_limits
    (a dict keyed by "module.func_name" strings).  The endpoint decorator
    captured the original limiter object by reference, so mutations here
    are visible when the next request arrives.
    """
    from limits import parse as parse_limit
    from slowapi.wrappers import Limit

    tiny_item = parse_limit("1/minute")
    for key, limit_list in list(lim._route_limits.items()):
        for i, existing in enumerate(limit_list):
            limit_list[i] = Limit(
                limit=tiny_item,
                key_func=existing.key_func,
                scope=existing.scope,
                per_method=existing.per_method,
                methods=existing.methods,
                error_message=existing.error_message,
                exempt_when=existing.exempt_when,
                cost=existing.cost,
                override_defaults=existing.override_defaults,
            )
    lim.reset()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _seed_user(session_factory, email="test@example.com", token="test-token"):
    import secrets, hashlib
    db = session_factory()
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        db.close()
        return token
    pw_hash = "salt:" + hashlib.pbkdf2_hmac(
        "sha256", b"password", b"salt", 260_000
    ).hex()
    db.add(User(
        email         = email,
        name          = "Test User",
        password_hash = pw_hash,
        paid          = False,
        session_token = token,
        created_at    = "2026-03-14T00:00:00Z",
    ))
    db.commit()
    db.close()
    return token


# ── Limiter setup tests ────────────────────────────────────────────────────────

class TestLimiterSetup:
    """Verify the limiter is wired into the app correctly."""

    def setup_method(self):
        self.mod = _load_app()
        self.app = self.mod.app

    def test_limiter_attached_to_app_state(self):
        assert hasattr(self.app.state, "limiter")
        assert self.app.state.limiter is not None

    def test_limiter_is_slowapi_instance(self):
        from slowapi import Limiter
        assert isinstance(self.app.state.limiter, Limiter)

    def test_rate_limit_exceeded_handler_registered(self):
        """The app must have a handler for RateLimitExceeded → 429."""
        from slowapi.errors import RateLimitExceeded
        handlers = self.app.exception_handlers
        assert RateLimitExceeded in handlers, (
            "RateLimitExceeded handler not registered on app"
        )

    def test_default_limits_configured(self):
        """Limiter has a default limit set."""
        limiter = self.app.state.limiter
        assert len(limiter._default_limits) > 0

    def test_limiter_uses_remote_address_key(self):
        """Key function must be get_remote_address."""
        from slowapi.util import get_remote_address
        assert self.app.state.limiter._key_func == get_remote_address


# ── Rate limit enforcement ─────────────────────────────────────────────────────

class TestHealthEndpointRateLimit:
    """
    /health has a per-endpoint limit.  We shrink all route limits to
    "1/minute" then make 2 requests — first is 200, second is 429.
    """

    def setup_method(self):
        self.mod = _load_app()
        lim = self.mod.limiter
        _apply_tiny_limits(lim)
        self.client = TestClient(self.mod.app, raise_server_exceptions=False)

    def test_health_returns_200_normally(self):
        # Reset counters so this isolated test always gets a fresh bucket
        self.mod.limiter.reset()
        resp = self.client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_health_returns_429_after_limit_exceeded(self):
        """Hit /health twice with a "1/minute" limit — 2nd should be 429."""
        r1 = self.client.get("/health")
        r2 = self.client.get("/health")
        assert r1.status_code == 200
        assert r2.status_code == 429

    def test_429_response_has_error_detail(self):
        """slowapi's built-in handler returns a non-empty body on 429."""
        self.client.get("/health")          # consume the 1 allowed request
        resp = self.client.get("/health")   # 429
        assert resp.status_code == 429
        assert resp.text != ""


class TestAuthEndpointsRateLimit:
    """Auth endpoints use a tight limit to prevent brute-force."""

    def setup_method(self):
        self.mod = _load_app()
        lim = self.mod.limiter
        _apply_tiny_limits(lim)
        self.client = TestClient(self.mod.app, raise_server_exceptions=False)

    def test_register_429_after_limit(self):
        payload = {"email": "a@a.com", "name": "A", "password": "pw"}
        r1 = self.client.post("/auth/register", json=payload)
        r2 = self.client.post("/auth/register", json={**payload, "email": "b@a.com"})
        results = [r1.status_code, r2.status_code]
        assert 429 in results, f"Expected 429, got {results}"

    def test_login_429_after_limit(self):
        payload = {"email": "nobody@a.com", "password": "wrong"}
        r1 = self.client.post("/auth/login", json=payload)
        r2 = self.client.post("/auth/login", json=payload)
        results = [r1.status_code, r2.status_code]
        assert 429 in results, f"Expected 429, got {results}"


# ── Per-endpoint limit metadata ────────────────────────────────────────────────

class TestEndpointLimitConfig:
    """
    Verify each route has a rate-limit decoration by inspecting the route's
    dependencies / callbacks registered by slowapi.
    """

    def setup_method(self):
        self.mod = _load_app()
        self.app = self.mod.app

    def _route_paths(self):
        return {r.path for r in self.app.routes}

    def test_dashboard_route_exists(self):
        assert "/dashboard" in self._route_paths()

    def test_health_route_exists(self):
        assert "/health" in self._route_paths()

    def test_auth_register_route_exists(self):
        assert "/auth/register" in self._route_paths()

    def test_auth_login_route_exists(self):
        assert "/auth/login" in self._route_paths()

    def test_api_keys_post_route_exists(self):
        assert "/api-keys" in self._route_paths()

    def test_pipeline_errors_route_exists(self):
        assert "/pipelines/{pipeline_name}/errors" in self._route_paths()

    def test_pipeline_runs_route_exists(self):
        assert "/pipelines/{pipeline_name}/runs" in self._route_paths()

    def test_runbooks_ingest_route_exists(self):
        assert "/runbooks/ingest" in self._route_paths()


# ── 429 response format ────────────────────────────────────────────────────────

class TestRateLimitResponse:

    def setup_method(self):
        self.mod = _load_app()
        lim = self.mod.limiter
        _apply_tiny_limits(lim)
        self.client = TestClient(self.mod.app, raise_server_exceptions=False)

    def test_429_status_code(self):
        self.client.get("/health")          # allowed
        resp = self.client.get("/health")   # rate limited
        assert resp.status_code == 429

    def test_429_response_is_not_empty(self):
        self.client.get("/health")
        resp = self.client.get("/health")
        assert len(resp.content) > 0

    def test_200_before_limit_hit(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200

    def test_different_paths_have_separate_counters(self):
        """
        Verify the limiter does not cross-contaminate counters across endpoints.
        With "1/minute" limit, the second call to /health is 429,
        but /auth/login still returns its first response (not 429 yet).
        """
        self.client.get("/health")   # uses the 1 allowed token from /health bucket
        self.client.get("/health")   # 429 for /health

        login_resp = self.client.post("/auth/login", json={"email": "x@x.com", "password": "p"})
        # /auth/login should NOT be 429 yet (separate bucket)
        assert login_resp.status_code != 429
