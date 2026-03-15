import sys
import os
import hashlib
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(PROJECT_ROOT)
sys.path.append(os.path.join(PROJECT_ROOT, 'services', 'log-processing-layer'))

from services.shared.models import Base, Pipeline, PipelineRun, Error, User, RunbookChunk, ApiKey

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://debugger:debugger@localhost:5433/pipeline_debugger"
)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ── Password helpers (stdlib only) ────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}:{digest.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest_hex = stored.split(":", 1)
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return secrets.compare_digest(check.hex(), digest_hex)
    except Exception:
        return False

# ── API key helpers ────────────────────────────────────────────────────────────

def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.
    Returns (full_key, prefix, sha256_hash).

    Format: dpd_<64 lowercase hex chars>
    Only the hash is stored; the full key is shown once and then discarded.
    """
    raw      = secrets.token_hex(32)          # 64 hex chars
    full_key = f"dpd_{raw}"
    prefix   = full_key[:12]                  # "dpd_" + 8 chars
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, prefix, key_hash

def _set_rls_workspace(db: Session, workspace_id: str) -> None:
    """
    SET LOCAL app.workspace_id for the current transaction so PostgreSQL RLS
    policies can enforce tenant isolation at the DB level.
    No-op on SQLite (used in tests).
    """
    try:
        db.execute(text("SET LOCAL app.workspace_id = :ws"), {"ws": workspace_id})
    except Exception:
        pass  # SQLite or non-PostgreSQL backend — RLS not supported

# ── Pydantic schemas ───────────────────────────────────────────────────────────

class PipelineStatus(BaseModel):
    name: str
    status: str
    lastRun: str

class ErrorItem(BaseModel):
    pipeline: str
    error: str
    rootCause: str
    fix: str
    detectedAt: str | None = None
    rawLog: str | None = None

class RunItem(BaseModel):
    runId: str
    status: str
    createdAt: str

class DashboardData(BaseModel):
    pipelines: List[PipelineStatus]
    errors: List[ErrorItem]

class ApiKeyCreate(BaseModel):
    name: str   # friendly label, e.g. "airflow-prod"

class ApiKeyOut(BaseModel):
    id:         int
    name:       str
    key_prefix: str   # first 12 chars — safe to display
    created_at: str
    is_active:  bool

class ApiKeyCreated(BaseModel):
    """Returned once on creation. key is NOT stored — show it to the user now."""
    id:         int
    name:       str
    key:        str   # full dpd_... value — shown ONCE
    key_prefix: str
    created_at: str

class RegisterRequest(BaseModel):
    email: str
    name: str | None = None
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class PaymentRequest(BaseModel):
    plan: str   # 'starter' | 'pro' | 'enterprise'

class UserOut(BaseModel):
    email: str
    name: str | None
    paid: bool
    plan: str | None
    is_admin: bool = False

class AuthResponse(BaseModel):
    token: str
    user: UserOut
    api_key: Optional[str] = None

# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        # ── Column additions (safe: IF NOT EXISTS) ────────────────────────────
        conn.execute(text("ALTER TABLE errors         ADD COLUMN IF NOT EXISTS detected_at  VARCHAR"))
        conn.execute(text("ALTER TABLE errors         ADD COLUMN IF NOT EXISTS raw_log      TEXT"))
        conn.execute(text("ALTER TABLE pipelines      ADD COLUMN IF NOT EXISTS workspace_id VARCHAR NOT NULL DEFAULT 'default'"))
        conn.execute(text("ALTER TABLE pipeline_runs  ADD COLUMN IF NOT EXISTS workspace_id VARCHAR NOT NULL DEFAULT 'default'"))
        conn.execute(text("ALTER TABLE errors         ADD COLUMN IF NOT EXISTS workspace_id VARCHAR NOT NULL DEFAULT 'default'"))

        # ── NOT NULL enforcement (fill nulls first, then set constraint) ──────
        conn.execute(text("UPDATE pipelines      SET status   = 'Failed'   WHERE status   IS NULL"))
        conn.execute(text("UPDATE pipelines      SET last_run = 'Unknown'  WHERE last_run IS NULL"))
        conn.execute(text("UPDATE pipeline_runs  SET status   = 'Failed'   WHERE status   IS NULL"))
        conn.execute(text("UPDATE pipeline_runs  SET created_at = now()::text WHERE created_at IS NULL"))
        conn.execute(text("ALTER TABLE pipelines     ALTER COLUMN name     SET NOT NULL"))
        conn.execute(text("ALTER TABLE pipelines     ALTER COLUMN status   SET NOT NULL"))
        conn.execute(text("ALTER TABLE pipelines     ALTER COLUMN last_run SET NOT NULL"))
        conn.execute(text("ALTER TABLE pipeline_runs ALTER COLUMN pipeline_name SET NOT NULL"))
        conn.execute(text("ALTER TABLE pipeline_runs ALTER COLUMN run_id     SET NOT NULL"))
        conn.execute(text("ALTER TABLE pipeline_runs ALTER COLUMN status     SET NOT NULL"))
        conn.execute(text("ALTER TABLE pipeline_runs ALTER COLUMN created_at SET NOT NULL"))
        conn.execute(text("ALTER TABLE errors        ALTER COLUMN pipeline_name SET NOT NULL"))
        conn.execute(text("ALTER TABLE errors        ALTER COLUMN error_type    SET NOT NULL"))

        # ── CHECK constraints (IF NOT EXISTS via DO block) ────────────────────
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'ck_pipelines_status'
                ) THEN
                    ALTER TABLE pipelines ADD CONSTRAINT ck_pipelines_status
                        CHECK (status IN ('Failed', 'Success'));
                END IF;
            END $$;
        """))
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'ck_pipeline_runs_status'
                ) THEN
                    ALTER TABLE pipeline_runs ADD CONSTRAINT ck_pipeline_runs_status
                        CHECK (status IN ('Failed', 'Success'));
                END IF;
            END $$;
        """))
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'ck_users_plan'
                ) THEN
                    ALTER TABLE users ADD CONSTRAINT ck_users_plan
                        CHECK (plan IN ('starter', 'pro', 'enterprise'));
                END IF;
            END $$;
        """))

        # ── Workspace-scoped unique key on pipelines (replaces global unique on name) ──
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_pipelines_workspace_name'
                ) THEN
                    ALTER TABLE pipelines DROP CONSTRAINT IF EXISTS pipelines_name_key;
                    ALTER TABLE pipelines ADD CONSTRAINT uq_pipelines_workspace_name
                        UNIQUE (workspace_id, name);
                END IF;
            END $$;
        """))

        # ── Workspace-scoped unique key on errors ─────────────────────────────
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_errors_workspace_pipeline_error'
                ) THEN
                    ALTER TABLE errors DROP CONSTRAINT IF EXISTS uq_errors_pipeline_error;
                    ALTER TABLE errors ADD CONSTRAINT uq_errors_workspace_pipeline_error
                        UNIQUE (workspace_id, pipeline_name, error_type);
                END IF;
            END $$;
        """))

        # ── pgvector extension + embedding column + HNSW index ───────────────
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("ALTER TABLE errors ADD COLUMN IF NOT EXISTS embedding vector(384)"))
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE indexname = 'ix_errors_embedding_hnsw'
                ) THEN
                    CREATE INDEX ix_errors_embedding_hnsw
                        ON errors USING hnsw (embedding vector_cosine_ops)
                        WITH (m = 16, ef_construction = 64);
                END IF;
            END $$;
        """))

        # ── Workspace indexes for fast tenant-scoped queries ─────────────────
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pipelines_workspace     ON pipelines(workspace_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pipeline_runs_workspace ON pipeline_runs(workspace_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_errors_workspace        ON errors(workspace_id)"))

        # ── runbook_chunks table + vector index ───────────────────────────────
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS runbook_chunks (
                id            SERIAL PRIMARY KEY,
                workspace_id  VARCHAR NOT NULL,
                source_file   VARCHAR NOT NULL,
                chunk_index   INTEGER NOT NULL,
                section_title VARCHAR,
                chunk_text    TEXT    NOT NULL,
                created_at    VARCHAR NOT NULL,
                embedding     vector(384),
                CONSTRAINT uq_runbook_chunks_workspace_file_idx
                    UNIQUE (workspace_id, source_file, chunk_index)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_runbook_chunks_workspace ON runbook_chunks(workspace_id)"
        ))
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE indexname = 'ix_runbook_chunks_embedding_hnsw'
                ) THEN
                    CREATE INDEX ix_runbook_chunks_embedding_hnsw
                        ON runbook_chunks USING hnsw (embedding vector_cosine_ops)
                        WITH (m = 16, ef_construction = 64);
                END IF;
            END $$;
        """))

        # ── server_default for users.paid ─────────────────────────────────────
        conn.execute(text("ALTER TABLE users ALTER COLUMN paid SET DEFAULT false"))

        # ── api_keys table ────────────────────────────────────────────────────
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id           SERIAL PRIMARY KEY,
                workspace_id VARCHAR NOT NULL,
                name         VARCHAR NOT NULL,
                key_prefix   VARCHAR NOT NULL,
                key_hash     VARCHAR NOT NULL,
                created_at   VARCHAR NOT NULL,
                is_active    BOOLEAN NOT NULL DEFAULT true,
                CONSTRAINT uq_api_keys_workspace_name UNIQUE (workspace_id, name),
                CONSTRAINT uq_api_keys_hash           UNIQUE (key_hash)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_api_keys_workspace ON api_keys(workspace_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_api_keys_hash ON api_keys(key_hash)"))

        # ── is_admin column on users ──────────────────────────────────────────
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false"))
        admin_emails_raw = os.getenv("ADMIN_EMAILS", "")
        if admin_emails_raw.strip():
            for ae in admin_emails_raw.split(","):
                ae = ae.strip()
                if ae:
                    conn.execute(text("UPDATE users SET is_admin = true WHERE email = :e"), {"e": ae})

        # ── PostgreSQL Row-Level Security (defense-in-depth) ──────────────────
        # Policies enforce workspace_id isolation at the DB layer, on top of
        # the existing workspace_id filters in application queries.
        # current_setting('app.workspace_id', true) returns NULL (not error) when
        # unset, which means NO rows match — fail-safe behaviour.
        try:
            for tbl in ("pipelines", "pipeline_runs", "errors", "runbook_chunks"):
                conn.execute(text(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY"))
                conn.execute(text(f"""
                    DO $$ BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_policies
                            WHERE tablename = '{tbl}' AND policyname = 'ws_isolation'
                        ) THEN
                            CREATE POLICY ws_isolation ON {tbl}
                                USING (workspace_id = current_setting('app.workspace_id', true));
                        END IF;
                    END $$;
                """))
        except Exception as rls_err:
            print(f"[api-layer] RLS setup skipped (non-PostgreSQL backend): {rls_err}")

        conn.commit()
    yield

# ── Rate limiter ───────────────────────────────────────────────────────────────
# Keys by client IP by default.  Storage: in-memory (single-instance).
# For multi-instance deployments, switch to storage_uri="redis://..." .
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

app = FastAPI(title="AI Pipeline Debugger API", version="0.2.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
_allowed_origins = [o.strip() for o in _raw_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── DB dependency ──────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ── Auth dependency ────────────────────────────────────────────────────────────

def get_current_user(
    x_session_token: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not x_session_token:
        raise HTTPException(status_code=401, detail="Missing session token")
    user = db.query(User).filter(User.session_token == x_session_token).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    return user

def _user_out(user: User) -> dict:
    return {"email": user.email, "name": user.name, "paid": user.paid, "plan": user.plan, "is_admin": getattr(user, 'is_admin', False)}

def _workspace(user: User) -> str:
    """Each user is their own tenant. workspace_id = str(user.id)."""
    return str(user.id)

def _auto_create_api_key(user: User, db: Session) -> str:
    """Create a default API key for a newly registered user. Returns the raw key (shown once)."""
    full_key, prefix, key_hash = generate_api_key()
    db.add(ApiKey(
        workspace_id = str(user.id),
        name         = "default",
        key_prefix   = prefix,
        key_hash     = key_hash,
        created_at   = datetime.now(timezone.utc).isoformat(),
        is_active    = True,
    ))
    db.commit()
    return full_key

# ── Auth endpoints ─────────────────────────────────────────────────────────────

@app.post("/auth/register", response_model=AuthResponse, status_code=201)
@limiter.limit("10/minute")
def register(request: Request, req: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    token = secrets.token_urlsafe(32)
    user  = User(
        email         = req.email,
        name          = req.name,
        password_hash = hash_password(req.password),
        paid          = False,
        session_token = token,
        created_at    = datetime.now(timezone.utc).isoformat(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    raw_key = _auto_create_api_key(user, db)
    return {"token": token, "user": _user_out(user), "api_key": raw_key}

@app.post("/auth/login", response_model=AuthResponse)
@limiter.limit("10/minute")
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    # Rotate session token on every login
    user.session_token = secrets.token_urlsafe(32)
    db.commit()
    return {"token": user.session_token, "user": _user_out(user)}

@app.get("/auth/me", response_model=UserOut)
@limiter.limit("60/minute")
def me(request: Request, current_user: User = Depends(get_current_user)):
    return _user_out(current_user)

class GoogleAuthRequest(BaseModel):
    access_token: str

@app.post("/auth/google", response_model=AuthResponse)
@limiter.limit("20/minute")
def google_auth(request: Request, req: GoogleAuthRequest, db: Session = Depends(get_db)):
    import requests as req_lib
    resp = req_lib.get(
        "https://www.googleapis.com/oauth2/v1/userinfo",
        params={"access_token": req.access_token},
        timeout=5,
    )
    if not resp.ok:
        raise HTTPException(status_code=401, detail="Invalid Google access token")
    info  = resp.json()
    email = info.get("email")
    name  = info.get("name") or email.split("@")[0]
    if not email:
        raise HTTPException(status_code=401, detail="Google account has no email")

    user = db.query(User).filter(User.email == email).first()
    if user:
        user.session_token = secrets.token_urlsafe(32)
    else:
        user = User(
            email         = email,
            name          = name,
            password_hash = "",   # Google users have no password
            paid          = False,
            session_token = secrets.token_urlsafe(32),
            created_at    = datetime.now(timezone.utc).isoformat(),
        )
        db.add(user)
    db.commit()
    db.refresh(user)
    raw_key = None
    existing_key = db.query(ApiKey).filter(ApiKey.workspace_id == str(user.id)).first()
    if not existing_key:
        raw_key = _auto_create_api_key(user, db)
    return {"token": user.session_token, "user": _user_out(user), "api_key": raw_key}

@app.post("/auth/payment", response_model=UserOut)
@limiter.limit("10/minute")
def complete_payment(
    request: Request,
    req: PaymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.paid = True
    current_user.plan = req.plan
    db.commit()
    db.refresh(current_user)
    return _user_out(current_user)

@app.delete("/auth/session", status_code=204)
@limiter.limit("20/minute")
def sign_out(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.session_token = None
    db.commit()

# ── Dashboard endpoints ────────────────────────────────────────────────────────

@app.get("/dashboard", response_model=DashboardData)
@limiter.limit("120/minute")
def get_dashboard_data(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws = _workspace(current_user)
    _set_rls_workspace(db, ws)
    pipelines = db.query(Pipeline).filter(Pipeline.workspace_id == ws).all()
    errors    = (
        db.query(Error)
        .filter(Error.workspace_id == ws)
        .order_by(Error.detected_at.desc())
        .all()
    )
    return {
        "pipelines": [{"name": p.name, "status": p.status, "lastRun": p.last_run} for p in pipelines],
        "errors":    [{"pipeline": e.pipeline_name, "error": e.error_type, "rootCause": e.root_cause, "fix": e.fix, "detectedAt": e.detected_at, "rawLog": e.raw_log} for e in errors],
    }

@app.get("/pipelines/{pipeline_name}/errors", response_model=List[ErrorItem])
@limiter.limit("120/minute")
def get_pipeline_errors(
    request: Request,
    pipeline_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws = _workspace(current_user)
    _set_rls_workspace(db, ws)
    if not db.query(Pipeline).filter(
        Pipeline.workspace_id == ws, Pipeline.name == pipeline_name
    ).first():
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_name}' not found")
    errors = (
        db.query(Error)
        .filter(Error.workspace_id == ws, Error.pipeline_name == pipeline_name)
        .order_by(Error.detected_at.desc())
        .all()
    )
    return [{"pipeline": e.pipeline_name, "error": e.error_type, "rootCause": e.root_cause, "fix": e.fix, "detectedAt": e.detected_at, "rawLog": e.raw_log} for e in errors]

@app.get("/pipelines/{pipeline_name}/runs", response_model=List[RunItem])
@limiter.limit("120/minute")
def get_pipeline_runs(
    request: Request,
    pipeline_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws = _workspace(current_user)
    _set_rls_workspace(db, ws)
    if not db.query(Pipeline).filter(
        Pipeline.workspace_id == ws, Pipeline.name == pipeline_name
    ).first():
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_name}' not found")
    runs = (
        db.query(PipelineRun)
        .filter(
            PipelineRun.workspace_id  == ws,
            PipelineRun.pipeline_name == pipeline_name,
        )
        .order_by(PipelineRun.created_at.desc())
        .all()
    )
    return [{"runId": r.run_id, "status": r.status, "createdAt": r.created_at} for r in runs]

@app.get("/health")
@limiter.limit("300/minute")
def health(request: Request):
    return {"status": "ok"}


# ── API key endpoints ──────────────────────────────────────────────────────────

@app.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
@limiter.limit("20/minute")
def create_api_key(
    request: Request,
    req: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate a new workspace-scoped API key.

    The full key is returned ONCE in this response and cannot be retrieved
    again — store it securely (e.g. in a secrets manager or env var).
    Subsequent calls to GET /api-keys show only the first 12 chars (prefix).
    """
    ws = _workspace(current_user)

    if db.query(ApiKey).filter(
        ApiKey.workspace_id == ws,
        ApiKey.name == req.name,
        ApiKey.is_active == True,
    ).first():
        raise HTTPException(status_code=409, detail=f"An active key named '{req.name}' already exists")

    full_key, prefix, key_hash = generate_api_key()
    now = datetime.now(timezone.utc).isoformat()

    key_record = ApiKey(
        workspace_id = ws,
        name         = req.name,
        key_prefix   = prefix,
        key_hash     = key_hash,
        created_at   = now,
        is_active    = True,
    )
    db.add(key_record)
    db.commit()
    db.refresh(key_record)

    return {
        "id":         key_record.id,
        "name":       key_record.name,
        "key":        full_key,      # shown ONCE — not stored
        "key_prefix": key_record.key_prefix,
        "created_at": key_record.created_at,
    }


@app.get("/api-keys", response_model=List[ApiKeyOut])
@limiter.limit("60/minute")
def list_api_keys(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all API keys for this workspace (active and revoked). Full key never shown."""
    ws = _workspace(current_user)
    keys = db.query(ApiKey).filter(ApiKey.workspace_id == ws).order_by(ApiKey.id).all()
    return [
        {
            "id":         k.id,
            "name":       k.name,
            "key_prefix": k.key_prefix,
            "created_at": k.created_at,
            "is_active":  k.is_active,
        }
        for k in keys
    ]


@app.delete("/api-keys/{key_id}", status_code=204)
@limiter.limit("20/minute")
def revoke_api_key(
    request: Request,
    key_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Revoke an API key (soft delete — is_active = False).
    The key record is retained for audit; revoked keys are immediately rejected
    on all endpoints that validate x-api-key.
    """
    ws = _workspace(current_user)
    key_record = db.query(ApiKey).filter(
        ApiKey.id == key_id,
        ApiKey.workspace_id == ws,
    ).first()
    if not key_record:
        raise HTTPException(status_code=404, detail="API key not found")
    key_record.is_active = False
    db.commit()


# ── Runbook ingestion endpoints ────────────────────────────────────────────────

AI_ENGINE_URL = os.getenv("AI_ENGINE_URL", "http://localhost:8002")

import requests as _requests
from runbook_ingester import ingest_runbook_text


class RunbookIngestRequest(BaseModel):
    """
    Payload for POST /runbooks/ingest.

    Send the raw markdown text of one runbook file. The API will chunk it,
    embed each chunk via the ai-engine, and store everything in runbook_chunks.
    Subsequent calls with the same source_file replace the existing chunks
    (delete-then-insert), so re-ingestion after edits is safe.
    """
    source_file:   str   # e.g. "spark_oom_runbook.md"
    markdown_text: str   # full file contents


class RunbookIngestResponse(BaseModel):
    source_file:    str
    chunks_stored:  int
    chunks_failed:  int   # chunks where embedding call failed (stored with null embedding)


@app.post("/runbooks/ingest", response_model=RunbookIngestResponse, status_code=201)
@limiter.limit("10/minute")
def ingest_runbook(
    request: Request,
    req: RunbookIngestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Ingest a markdown runbook into the RAG vector store.

    Pipeline:
      1. Chunk the markdown by headers + paragraph boundaries.
      2. Embed each chunk via ai-engine POST /embed (sentence-transformers).
      3. Delete existing chunks for this (workspace, source_file) pair.
      4. Bulk insert new chunks with their embeddings.

    The chunks become immediately available for retrieval on the next error event.
    """
    ws = _workspace(current_user)

    # Step 1: chunk
    rows = ingest_runbook_text(
        markdown_text = req.markdown_text,
        source_file   = req.source_file,
        workspace_id  = ws,
    )

    if not rows:
        raise HTTPException(status_code=422, detail="No valid chunks extracted from markdown.")

    # Step 2: embed each chunk (call ai-engine)
    stored = 0
    failed = 0

    for row in rows:
        try:
            resp = _requests.post(
                f"{AI_ENGINE_URL}/embed",
                json={"text": row.chunk_text},
                timeout=30,
            )
            if resp.status_code == 200:
                row.embedding = resp.json().get("embedding")
        except Exception as e:
            print(f"[api-layer] Runbook embed failed for chunk {row.chunk_index}: {e}")

    # Step 3: delete old chunks for this (workspace, source_file)
    db.query(RunbookChunk).filter(
        RunbookChunk.workspace_id == ws,
        RunbookChunk.source_file  == req.source_file,
    ).delete(synchronize_session=False)

    # Step 4: bulk insert
    for row in rows:
        db_chunk = RunbookChunk(
            workspace_id  = row.workspace_id,
            source_file   = row.source_file,
            chunk_index   = row.chunk_index,
            section_title = row.section_title,
            chunk_text    = row.chunk_text,
            created_at    = row.created_at,
            embedding     = row.embedding,
        )
        db.add(db_chunk)
        if row.embedding:
            stored += 1
        else:
            failed += 1

    db.commit()

    return {
        "source_file":   req.source_file,
        "chunks_stored": stored + failed,   # all chunks stored; some without embedding
        "chunks_failed": failed,
    }


@app.get("/runbooks", response_model=List[dict])
@limiter.limit("60/minute")
def list_runbooks(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all ingested runbook files for this workspace, with chunk counts.
    """
    ws = _workspace(current_user)
    from sqlalchemy import func
    rows = (
        db.query(RunbookChunk.source_file, func.count(RunbookChunk.id).label("chunks"))
        .filter(RunbookChunk.workspace_id == ws)
        .group_by(RunbookChunk.source_file)
        .all()
    )
    return [{"source_file": r.source_file, "chunks": r.chunks} for r in rows]


# ── Admin endpoints ────────────────────────────────────────────────────────────

def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if not getattr(current_user, 'is_admin', False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

@app.get("/admin/stats")
@limiter.limit("60/minute")
def admin_stats(request: Request, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    from sqlalchemy import func
    total_users  = db.query(func.count(User.id)).scalar()
    paid_users   = db.query(func.count(User.id)).filter(User.paid == True).scalar()
    by_plan      = {row[0]: row[1] for row in db.query(User.plan, func.count(User.id)).group_by(User.plan).all()}
    total_pipelines = db.query(func.count(Pipeline.id)).scalar()
    total_errors    = db.query(func.count(Error.id)).scalar()
    total_runs      = db.query(func.count(PipelineRun.id)).scalar()
    recent_users = db.query(User).order_by(User.created_at.desc()).limit(10).all()
    return {
        "total_users":    total_users,
        "paid_users":     paid_users,
        "free_users":     total_users - paid_users,
        "by_plan":        by_plan,
        "total_pipelines": total_pipelines,
        "total_errors":   total_errors,   # approximates Claude API calls
        "total_runs":     total_runs,
        "recent_signups": [_user_out(u) for u in recent_users],
    }

@app.get("/admin/users")
@limiter.limit("60/minute")
def admin_users(request: Request, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    from sqlalchemy import func
    users = db.query(User).order_by(User.created_at.desc()).all()
    result = []
    for u in users:
        ws = str(u.id)
        pipelines = db.query(func.count(Pipeline.id)).filter(Pipeline.workspace_id == ws).scalar()
        errors    = db.query(func.count(Error.id)).filter(Error.workspace_id == ws).scalar()
        runs      = db.query(func.count(PipelineRun.id)).filter(PipelineRun.workspace_id == ws).scalar()
        api_key   = db.query(ApiKey).filter(ApiKey.workspace_id == ws, ApiKey.is_active == True).first()
        result.append({
            **_user_out(u),
            "id":             u.id,
            "created_at":     u.created_at,
            "pipeline_count": pipelines,
            "error_count":    errors,
            "run_count":      runs,
            "api_key_prefix": api_key.key_prefix if api_key else None,
        })
    return result


@app.delete("/runbooks/{source_file}", status_code=204)
@limiter.limit("20/minute")
def delete_runbook(
    request: Request,
    source_file: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete all chunks for a given runbook file from this workspace."""
    ws = _workspace(current_user)
    db.query(RunbookChunk).filter(
        RunbookChunk.workspace_id == ws,
        RunbookChunk.source_file  == source_file,
    ).delete(synchronize_session=False)
    db.commit()
