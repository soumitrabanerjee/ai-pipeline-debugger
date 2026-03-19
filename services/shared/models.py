from sqlalchemy import Column, Integer, String, Boolean, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import declarative_base

# pgvector is optional — falls back to String when package not installed (e.g. in unit tests)
try:
    from pgvector.sqlalchemy import Vector
    _EMBED_COL = lambda: Column(Vector(384), nullable=True)  # noqa: E731
except ImportError:
    _EMBED_COL = lambda: Column(String, nullable=True)  # noqa: E731

Base = declarative_base()

EMBED_DIM = 384  # all-MiniLM-L6-v2 output dimension


class Pipeline(Base):
    """
    Represents a data pipeline being monitored.

    Rules:
      - (workspace_id, name) is the natural composite key — unique per tenant.
      - status must be 'Failed' or 'Success' (CHECK constraint).
      - last_run stores the ISO-8601 timestamp of the most recent ingest.
    """
    __tablename__ = "pipelines"
    __table_args__ = (
        CheckConstraint("status IN ('Failed', 'Success')", name="ck_pipelines_status"),
        UniqueConstraint("workspace_id", "name", name="uq_pipelines_workspace_name"),
    )

    id           = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(String,  nullable=False, index=True, server_default="default")
    name         = Column(String,  nullable=False, index=True)
    status       = Column(String,  nullable=False)
    last_run     = Column(String,  nullable=False)


class PipelineRun(Base):
    """
    Tracks every individual execution of a pipeline.

    Rules:
      - run_id is the natural key (unique globally, NOT NULL, indexed).
      - (workspace_id, pipeline_name) references pipelines scoped to tenant.
      - status must be 'Failed' or 'Success' (CHECK constraint).
      - created_at stores the ISO-8601 timestamp from the originating log event.
    """
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint("status IN ('Failed', 'Success')", name="ck_pipeline_runs_status"),
    )

    id            = Column(Integer, primary_key=True, index=True)
    workspace_id  = Column(String,  nullable=False, index=True, server_default="default")
    pipeline_name = Column(String,  nullable=False, index=True)
    run_id        = Column(String,  unique=True, index=True, nullable=False)
    status        = Column(String,  nullable=False)
    created_at    = Column(String,  nullable=False)   # ISO-8601


class User(Base):
    """
    A registered SaaS user. Each user is their own tenant (workspace_id = str(user.id)).

    Rules:
      - email is the natural key (unique, NOT NULL, indexed, lowercase enforced by app).
      - password_hash stores 'salt:pbkdf2_sha256_hex' — never plain-text.
      - paid defaults to FALSE at DB level (server_default).
      - plan is constrained to known tier values or NULL (unpaid users).
      - session_token is unique; set to NULL on sign-out (server-side invalidation).
      - created_at is an ISO-8601 string set once at registration.
    """
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "plan IN ('starter', 'pro', 'enterprise')",
            name="ck_users_plan",
        ),
    )

    id            = Column(Integer, primary_key=True, index=True)
    email         = Column(String,  unique=True, index=True, nullable=False)
    name          = Column(String,  nullable=True)
    password_hash = Column(String,  nullable=False)
    paid          = Column(Boolean, nullable=False, default=False, server_default="false")
    plan          = Column(String,  nullable=True)
    session_token = Column(String,  nullable=True, unique=True, index=True)
    created_at    = Column(String,  nullable=False)
    is_admin      = Column(Boolean, nullable=False, default=False, server_default="false")
    ai_calls_used  = Column(Integer, nullable=False, default=0,   server_default="0")
    ai_calls_limit = Column(Integer, nullable=False, default=100, server_default="100")
    last_grant_at  = Column(String,  nullable=True)   # ISO-8601; set on each admin grant


class PendingRegistration(Base):
    """
    Temporary holding area for signups awaiting email OTP verification.

    A row is created when the user submits the signup form. It is deleted
    (and a real User + ApiKey row created atomically) only after the correct
    OTP is submitted. If verification never happens the row stays here until
    the next signup attempt with the same email, at which point a fresh OTP
    is issued and the old row is replaced.

    No User row is written until verification succeeds — this keeps the
    users table clean and prevents orphaned / unverified accounts.
    """
    __tablename__ = "pending_registrations"

    id             = Column(Integer, primary_key=True, index=True)
    email          = Column(String,  unique=True, index=True, nullable=False)
    name           = Column(String,  nullable=True)
    password_hash  = Column(String,  nullable=False)
    otp_code       = Column(String,  nullable=False)
    otp_expires_at = Column(String,  nullable=False)
    created_at     = Column(String,  nullable=False)


class RunbookChunk(Base):
    """
    A single chunk of an internal runbook document, stored with its embedding
    for semantic retrieval during AI root-cause analysis.

    Ingestion pipeline:
      markdown file → header-aware chunker → sentence-transformers → this table

    Retrieval:
      error embedding → KNN cosine search → top-K chunks → Claude prompt context

    Rules:
      - (workspace_id, source_file, chunk_index) is the natural composite key.
      - chunk_text stores the raw markdown text of the chunk (≤600 chars).
      - embedding is a 384-dim vector from all-MiniLM-L6-v2.
      - source_file is the original filename (e.g. "spark_oom_runbook.md").
      - section_title is the nearest ## heading above the chunk (for citations).
    """
    __tablename__ = "runbook_chunks"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "source_file", "chunk_index",
            name="uq_runbook_chunks_workspace_file_idx",
        ),
    )

    id            = Column(Integer, primary_key=True, index=True)
    workspace_id  = Column(String,  nullable=False, index=True)
    source_file   = Column(String,  nullable=False, index=True)
    chunk_index   = Column(Integer, nullable=False)
    section_title = Column(String,  nullable=True)   # nearest ## heading
    chunk_text    = Column(String,  nullable=False)
    created_at    = Column(String,  nullable=False)
    embedding     = _EMBED_COL()


class ApiKey(Base):
    """
    Per-workspace API key for authenticating webhook and ingestion requests.

    Key format: dpd_<64 random hex chars>
    Only the SHA-256 hash is stored — the full key is shown exactly once at
    creation time and cannot be recovered afterwards.

    Rules:
      - key_hash is globally unique (indexed for fast lookup on every request).
      - key_prefix stores the first 12 chars (e.g. "dpd_ab12cd34")
        so users can identify which key is which without exposing the secret.
      - is_active = False means the key is revoked (soft delete).
      - (workspace_id, name) is unique so users can't create two keys with
        the same friendly name in the same workspace.
    """
    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_api_keys_workspace_name"),
    )

    id           = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(String,  nullable=False, index=True)
    name         = Column(String,  nullable=False)
    key_prefix   = Column(String,  nullable=False)   # first 12 chars for display
    key_hash     = Column(String,  nullable=False, unique=True, index=True)  # SHA-256
    created_at   = Column(String,  nullable=False)
    is_active    = Column(Boolean, nullable=False, default=True, server_default="true")


class Error(Base):
    """
    Stores the AI-analysed root cause for a pipeline error, plus its embedding
    vector for RAG-based retrieval of similar past incidents.

    Rules:
      - (workspace_id, pipeline_name, error_type) is the composite unique key —
        deduplication is tenant-scoped.
      - detected_at is updated to the latest failure timestamp on every upsert.
      - embedding stores a 384-dim sentence-transformers vector for KNN search.
    """
    __tablename__ = "errors"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "pipeline_name", "error_type",
            name="uq_errors_workspace_pipeline_error",
        ),
    )

    id            = Column(Integer, primary_key=True, index=True)
    workspace_id  = Column(String,  nullable=False, index=True, server_default="default")
    pipeline_name = Column(String,  nullable=False, index=True)
    error_type    = Column(String,  nullable=False)
    root_cause    = Column(String,  nullable=True)
    fix           = Column(String,  nullable=True)
    detected_at   = Column(String,  nullable=True)   # ISO-8601; newest failure wins
    raw_log       = Column(String,  nullable=True)   # scrubbed log text (≤10 000 chars)
    embedding     = _EMBED_COL()                      # vector(384) for pgvector KNN search
