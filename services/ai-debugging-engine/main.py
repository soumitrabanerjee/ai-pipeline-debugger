from fastapi import FastAPI
from pydantic import BaseModel
import random

app = FastAPI(title="AI Debugging Engine", version="0.1.0")

class ErrorAnalysisRequest(BaseModel):
    error_message: str
    pipeline_context: str | None = None

class ErrorAnalysisResponse(BaseModel):
    root_cause: str
    suggested_fix: str
    confidence_score: float

@app.post("/analyze", response_model=ErrorAnalysisResponse)
def analyze_error(request: ErrorAnalysisRequest):
    """
    Analyzes an error message and returns a root cause and suggested fix.
    Currently uses a heuristic-based mock AI.
    """
    error_msg = request.error_message.lower()
    
    # Mock AI Logic - Heuristics based on keywords
    if "spark" in error_msg and ("memory" in error_msg or "oom" in error_msg):
        return {
            "root_cause": "Spark executor ran out of memory due to large shuffle partition.",
            "suggested_fix": "Increase spark.executor.memory to 8g or increase spark.sql.shuffle.partitions.",
            "confidence_score": 0.95
        }
    elif "timeout" in error_msg or "timed out" in error_msg:
        return {
            "root_cause": "External service or database query took too long to respond.",
            "suggested_fix": "Check network connectivity or increase the timeout configuration (e.g., request_timeout_ms).",
            "confidence_score": 0.85
        }
    elif "permission" in error_msg or "access denied" in error_msg:
        return {
            "root_cause": "IAM role or service account lacks necessary permissions.",
            "suggested_fix": "Verify IAM policies and ensure the service account has read/write access to the resource.",
            "confidence_score": 0.90
        }
    elif "schema" in error_msg or "column" in error_msg:
        return {
            "root_cause": "Data schema mismatch between source and destination.",
            "suggested_fix": "Update the schema definition or add a transformation step to handle the schema change.",
            "confidence_score": 0.88
        }
    else:
        # Generic fallback
        return {
            "root_cause": "Unknown error pattern detected.",
            "suggested_fix": "Check application logs for more details and verify recent deployment changes.",
            "confidence_score": 0.50
        }

@app.get("/health")
def health():
    return {"status": "ok"}
