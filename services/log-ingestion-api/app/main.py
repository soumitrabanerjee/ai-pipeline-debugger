import sys
import os
import requests
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Add project root to Python path to allow importing from 'services'
# We go up three levels from services/log-ingestion-api/app/main.py to reach the project root.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(PROJECT_ROOT)

# Now we can import from the shared module
from services.shared.models import Base, Pipeline, Error

app = FastAPI(title="Log Ingestion API", version="0.1.0")

# Database Configuration
# Point to the same database file used by the API Layer
# We assume the API Layer is in ../api-layer relative to this file's directory (services/log-ingestion-api)
# The working directory when running uvicorn is services/log-ingestion-api

# Path to the DB file in services/api-layer
# Use absolute path to be safe, or relative from where uvicorn is run.
# Assuming uvicorn is run from services/log-ingestion-api
DB_PATH = "../api-layer/pipeline_debugger.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

print(f"Connecting to database at: {os.path.abspath(DB_PATH)}")

# connect_args={"check_same_thread": False} is needed for SQLite
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Pydantic Models
class LogEvent(BaseModel):
    source: str
    workspace_id: str
    job_id: str
    run_id: str
    task_id: str | None = None
    level: str
    timestamp: str
    message: str
    raw_log_uri: str | None = None

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def analyze_error_with_ai(error_message: str):
    """
    Calls the AI Debugging Engine to analyze the error.
    """
    try:
        response = requests.post(
            "http://localhost:8002/analyze",
            json={"error_message": error_message},
            timeout=5
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"AI Analysis failed: {e}")
    
    # Fallback if AI service is down or fails
    return {
        "root_cause": "Analysis Failed (AI Service Unavailable)",
        "suggested_fix": "Check logs manually."
    }

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.post("/ingest")
def ingest(event: LogEvent, db: Session = Depends(get_db)):
    # 1. Update Pipeline Status
    # We use job_id as the pipeline name for simplicity
    pipeline = db.query(Pipeline).filter(Pipeline.name == event.job_id).first()
    
    status = "Success"
    if event.level == "ERROR":
        status = "Failed"
    
    if pipeline:
        pipeline.status = status
        pipeline.last_run = "Just now" # In a real app, use event.timestamp
    else:
        # Create new pipeline if it doesn't exist
        pipeline = Pipeline(name=event.job_id, status=status, last_run="Just now")
        db.add(pipeline)
    
    # 2. If Error, create Error record with AI Analysis
    if event.level == "ERROR":
        # Simple heuristic to extract error type from message
        error_type = "UnknownError"
        if ":" in event.message:
            error_type = event.message.split(":")[0].strip()
        else:
            error_type = event.message[:50] # Use first 50 chars as error type if no colon
        
        # Call AI Service
        ai_analysis = analyze_error_with_ai(event.message)
        
        new_error = Error(
            pipeline_name=event.job_id,
            error_type=error_type,
            root_cause=ai_analysis.get("root_cause", "Pending Analysis"),
            fix=ai_analysis.get("suggested_fix", "Pending Analysis")
        )
        db.add(new_error)
    
    db.commit()

    return {"status": "accepted", "run_id": event.run_id}
