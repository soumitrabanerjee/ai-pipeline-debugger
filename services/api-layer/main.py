import sys
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Add project root to Python path to allow importing from 'services'
# This is a common pattern for non-packaged projects.
# We go up two levels from services/api-layer/main.py to reach the project root.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(PROJECT_ROOT)

# Now we can import from the shared module
from services.shared.models import Base, Pipeline, PipelineRun, Error

# Database Configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://debugger:debugger@localhost:5433/pipeline_debugger"
)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Pydantic Models (Schemas)
class PipelineCreate(BaseModel):
    name: str
    status: str
    last_run: str

class PipelineStatus(BaseModel):
    name: str
    status: str
    lastRun: str

class ErrorItem(BaseModel):
    pipeline: str
    error: str
    rootCause: str
    fix: str

class RunItem(BaseModel):
    runId: str
    status: str
    createdAt: str

class DashboardData(BaseModel):
    pipelines: List[PipelineStatus]
    errors: List[ErrorItem]

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if db.query(Pipeline).count() == 0:
        pipelines_data = [
            Pipeline(name="customer_etl", status="Failed", last_run="2 min ago"),
            Pipeline(name="billing_pipeline", status="Success", last_run="10 min ago"),
            Pipeline(name="analytics_daily", status="Failed", last_run="30 min ago"),
        ]
        db.add_all(pipelines_data)
        errors_data = [
            Error(pipeline_name="customer_etl", error_type="ExecutorLostFailure", root_cause="Spark executor memory exceeded", fix="Increase spark.executor.memory to 8g"),
            Error(pipeline_name="analytics_daily", error_type="SchemaMismatch", root_cause="Column type mismatch in parquet", fix="Update schema or cast column types"),
        ]
        db.add_all(errors_data)
        db.commit()
    db.close()
    yield

app = FastAPI(title="AI Pipeline Debugger API", version="0.1.0", lifespan=lifespan)

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.post("/pipelines", response_model=PipelineStatus)
def create_pipeline(pipeline: PipelineCreate, db: Session = Depends(get_db)):
    db_pipeline = Pipeline(name=pipeline.name, status=pipeline.status, last_run=pipeline.last_run)
    db.add(db_pipeline)
    db.commit()
    db.refresh(db_pipeline)
    return {"name": db_pipeline.name, "status": db_pipeline.status, "lastRun": db_pipeline.last_run}

@app.get("/dashboard", response_model=DashboardData)
def get_dashboard_data(db: Session = Depends(get_db)):
    pipelines = db.query(Pipeline).all()
    errors = db.query(Error).all()
    return {
        "pipelines": [{"name": p.name, "status": p.status, "lastRun": p.last_run} for p in pipelines],
        "errors": [{"pipeline": e.pipeline_name, "error": e.error_type, "rootCause": e.root_cause, "fix": e.fix} for e in errors]
    }

@app.get("/pipelines/{pipeline_name}/errors", response_model=List[ErrorItem])
def get_pipeline_errors(pipeline_name: str, db: Session = Depends(get_db)):
    pipeline = db.query(Pipeline).filter(Pipeline.name == pipeline_name).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_name}' not found")
    errors = db.query(Error).filter(Error.pipeline_name == pipeline_name).all()
    return [{"pipeline": e.pipeline_name, "error": e.error_type, "rootCause": e.root_cause, "fix": e.fix} for e in errors]

@app.get("/pipelines/{pipeline_name}/runs", response_model=List[RunItem])
def get_pipeline_runs(pipeline_name: str, db: Session = Depends(get_db)):
    pipeline = db.query(Pipeline).filter(Pipeline.name == pipeline_name).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_name}' not found")
    runs = (
        db.query(PipelineRun)
        .filter(PipelineRun.pipeline_name == pipeline_name)
        .order_by(PipelineRun.created_at.desc())
        .all()
    )
    return [{"runId": r.run_id, "status": r.status, "createdAt": r.created_at} for r in runs]

@app.get("/health")
def health():
    return {"status": "ok"}
