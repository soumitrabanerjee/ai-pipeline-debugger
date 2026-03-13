from sqlalchemy import Column, Integer, String, Boolean, CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base

# This is the single source of truth for our database schema.
Base = declarative_base()


class Pipeline(Base):
    """
    Represents a data pipeline being monitored.

    Rules:
      - name is the natural key (unique, NOT NULL, indexed).
      - status must be 'Failed' or 'Success' (CHECK constraint).
      - last_run is a human-readable label ("Just now", "2 min ago").
    """
    __tablename__ = "pipelines"
    __table_args__ = (
        CheckConstraint("status IN ('Failed', 'Success')", name="ck_pipelines_status"),
    )

    id       = Column(Integer, primary_key=True, index=True)
    name     = Column(String,  unique=True, index=True, nullable=False)
    status   = Column(String,  nullable=False)
    last_run = Column(String,  nullable=False)


class PipelineRun(Base):
    """
    Tracks every individual execution of a pipeline.

    Rules:
      - run_id is the natural key (unique, NOT NULL, indexed).
      - pipeline_name is a FK to pipelines.name (referential integrity).
      - status must be 'Failed' or 'Success' (CHECK constraint).
      - created_at stores the ISO-8601 timestamp from the originating log event.
    """
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint("status IN ('Failed', 'Success')", name="ck_pipeline_runs_status"),
    )

    id            = Column(Integer, primary_key=True, index=True)
    pipeline_name = Column(String,  ForeignKey("pipelines.name", ondelete="CASCADE"),
                           nullable=False, index=True)
    run_id        = Column(String,  unique=True, index=True, nullable=False)
    status        = Column(String,  nullable=False)
    created_at    = Column(String,  nullable=False)   # ISO-8601


class User(Base):
    """
    A registered SaaS user.

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


class Error(Base):
    """
    Stores the AI-analysed root cause for a pipeline error.

    Rules:
      - (pipeline_name, error_type) is a natural composite unique key — deduplication
        means repeated failures update the existing row rather than inserting new ones.
      - pipeline_name is a FK to pipelines.name (referential integrity).
      - detected_at is updated to the latest failure timestamp on every upsert.
    """
    __tablename__ = "errors"
    __table_args__ = (
        UniqueConstraint("pipeline_name", "error_type", name="uq_errors_pipeline_error"),
    )

    id            = Column(Integer, primary_key=True, index=True)
    pipeline_name = Column(String,  ForeignKey("pipelines.name", ondelete="CASCADE"),
                           nullable=False, index=True)
    error_type    = Column(String,  nullable=False)
    root_cause    = Column(String,  nullable=True)
    fix           = Column(String,  nullable=True)
    detected_at   = Column(String,  nullable=True)   # ISO-8601; newest failure wins
