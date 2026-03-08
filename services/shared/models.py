from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

# This is the single source of truth for our database schema.
Base = declarative_base()

class Pipeline(Base):
    """Represents a data pipeline being monitored."""
    __tablename__ = "pipelines"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    status = Column(String)
    last_run = Column(String)

class PipelineRun(Base):
    """Tracks every individual execution of a pipeline."""
    __tablename__ = "pipeline_runs"
    id = Column(Integer, primary_key=True, index=True)
    pipeline_name = Column(String, index=True)
    run_id = Column(String, unique=True, index=True)
    status = Column(String)       # "Failed" | "Success"
    created_at = Column(String)   # ISO-8601 timestamp from the log event

class Error(Base):
    """Represents a specific error event from a pipeline run."""
    __tablename__ = "errors"
    id = Column(Integer, primary_key=True, index=True)
    pipeline_name = Column(String, index=True)
    error_type = Column(String)
    root_cause = Column(String)
    fix = Column(String)
