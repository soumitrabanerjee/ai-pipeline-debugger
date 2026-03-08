from fastapi import FastAPI
from pydantic import BaseModel
import requests
import json
import re

app = FastAPI(title="AI Debugging Engine", version="0.1.0")

# Ollama Configuration — override OLLAMA_HOST for Docker
import os
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_URL = f"{OLLAMA_HOST}/api/generate"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

class ErrorAnalysisRequest(BaseModel):
    error_message: str
    pipeline_context: str | None = None

class ErrorAnalysisResponse(BaseModel):
    root_cause: str
    suggested_fix: str
    confidence_score: float

def clean_json_response(text: str) -> str:
    """
    Cleans the response to ensure it's valid JSON.
    """
    # Remove markdown code blocks if present
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    return text.strip()

@app.post("/analyze", response_model=ErrorAnalysisResponse)
def analyze_error(request: ErrorAnalysisRequest):
    """
    Analyzes an error message using Local Ollama (Llama 3.1) and returns a root cause and suggested fix.
    """
    error_msg = request.error_message
    context = request.pipeline_context or "No additional context provided."

    prompt = f"""
    You are an expert Site Reliability Engineer (SRE). Analyze the following error log from a data pipeline.

    Error Log:
    "{error_msg}"

    Context:
    {context}

    Provide a root cause analysis and a specific, actionable fix.
    Return your response in strict JSON format with the following keys:
    - "root_cause": A concise explanation of why the error occurred.
    - "suggested_fix": A specific command or configuration change to fix it.
    - "confidence_score": A number between 0.0 and 1.0 indicating your confidence.

    Do not include any markdown formatting or explanation outside the JSON.
    """

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",  # Force JSON output
        "stream": False    # Get the full response at once
    }

    print(f"Calling Ollama ({OLLAMA_MODEL}) at {OLLAMA_URL}...")

    try:
        # Increased timeout to 600 seconds for slower local inference
        response = requests.post(OLLAMA_URL, json=payload, timeout=600)

        print(f"Ollama Response Status: {response.status_code}")
        print(f"Ollama Raw Response: {response.text[:500]}...") # Print first 500 chars

        response.raise_for_status()

        data = response.json()
        content = data.get("response", "")

        # Parse the JSON response
        try:
            cleaned_text = clean_json_response(content)
            analysis = json.loads(cleaned_text)

            return {
                "root_cause": analysis.get("root_cause", "Analysis failed to extract root cause."),
                "suggested_fix": analysis.get("suggested_fix", "Analysis failed to extract fix."),
                "confidence_score": analysis.get("confidence_score", 0.5)
            }

        except json.JSONDecodeError as e:
            print(f"Failed to parse Ollama response: {e}")
            print(f"Raw response: {content}")
            return {
                "root_cause": "AI Analysis failed to parse response.",
                "suggested_fix": "Check logs manually.",
                "confidence_score": 0.0
            }

    except requests.RequestException as e:
        print(f"*** OLLAMA API REQUEST FAILED: {e} ***")
        return {
            "root_cause": "AI Service Unavailable (Ollama Connection Failed).",
            "suggested_fix": "Ensure Ollama is running (ollama serve).",
            "confidence_score": 0.0
        }

@app.get("/health")
def health():
    return {"status": "ok"}
