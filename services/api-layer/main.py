import sys
import os
import hashlib
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(PROJECT_ROOT)
sys.path.append(os.path.join(PROJECT_ROOT, 'services', 'log-processing-layer'))

from services.shared.models import Base, Pipeline, PipelineRun, Error, User, RunbookChunk

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

class RunItem(BaseModel):
    runId: str
    status: str
    createdAt: str

class DashboardData(BaseModel):
    pipelines: List[PipelineStatus]
    errors: List[ErrorItem]

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

class AuthResponse(BaseModel):
    token: str
    user: UserOut

# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        # ── Column additions (safe: IF NOT EXISTS) ────────────────────────────
        conn.execute(text("ALTER TABLE errors         ADD COLUMN IF NOT EXISTS detected_at  VARCHAR"))
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

        conn.commit()
    yield

app = FastAPI(title="AI Pipeline Debugger API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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
    return {"email": user.email, "name": user.name, "paid": user.paid, "plan": user.plan}

def _workspace(user: User) -> str:
    """Each user is their own tenant. workspace_id = str(user.id)."""
    return str(user.id)

# ── Auth endpoints ─────────────────────────────────────────────────────────────

@app.post("/auth/register", response_model=AuthResponse, status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
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
    return {"token": token, "user": _user_out(user)}

@app.post("/auth/login", response_model=AuthResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    # Rotate session token on every login
    user.session_token = secrets.token_urlsafe(32)
    db.commit()
    return {"token": user.session_token, "user": _user_out(user)}

@app.get("/auth/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return _user_out(current_user)

@app.post("/auth/payment", response_model=UserOut)
def complete_payment(
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
def sign_out(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.session_token = None
    db.commit()

# ── Dashboard endpoints ────────────────────────────────────────────────────────

@app.get("/dashboard", response_model=DashboardData)
def get_dashboard_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws        = _workspace(current_user)
    pipelines = db.query(Pipeline).filter(Pipeline.workspace_id == ws).all()
    errors    = (
        db.query(Error)
        .filter(Error.workspace_id == ws)
        .order_by(Error.detected_at.desc())
        .all()
    )
    return {
        "pipelines": [{"name": p.name, "status": p.status, "lastRun": p.last_run} for p in pipelines],
        "errors":    [{"pipeline": e.pipeline_name, "error": e.error_type, "rootCause": e.root_cause, "fix": e.fix, "detectedAt": e.detected_at} for e in errors],
    }

@app.get("/pipelines/{pipeline_name}/errors", response_model=List[ErrorItem])
def get_pipeline_errors(
    pipeline_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws = _workspace(current_user)
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
    return [{"pipeline": e.pipeline_name, "error": e.error_type, "rootCause": e.root_cause, "fix": e.fix, "detectedAt": e.detected_at} for e in errors]

@app.get("/pipelines/{pipeline_name}/runs", response_model=List[RunItem])
def get_pipeline_runs(
    pipeline_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws = _workspace(current_user)
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
def health():
    return {"status": "ok"}


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
def ingest_runbook(
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
def list_runbooks(
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


@app.delete("/runbooks/{source_file}", status_code=204)
def delete_runbook(
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
