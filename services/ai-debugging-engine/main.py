import json
import os
import re

import anthropic
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="AI Debugging Engine", version="0.1.0")

# Claude model — Haiku is the cheapest/fastest; override via env var
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# Instantiated once at startup; reads ANTHROPIC_API_KEY from environment
_client = anthropic.Anthropic()


class ErrorAnalysisRequest(BaseModel):
    error_message: str
    pipeline_context: str | None = None


class ErrorAnalysisResponse(BaseModel):
    root_cause: str
    suggested_fix: str
    confidence_score: float


def clean_json_response(text: str) -> str:
    """Strip markdown fences so the response can be parsed as JSON."""
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    return text.strip()


@app.post("/analyze", response_model=ErrorAnalysisResponse)
def analyze_error(request: ErrorAnalysisRequest):
    """
    Analyse a pipeline error using Claude and return a structured root cause + fix.
    """
    error_msg = request.error_message
    context   = request.pipeline_context or "No additional context provided."

    prompt = f"""You are an expert Site Reliability Engineer (SRE). \
Analyse the following error log from a data pipeline.

Error Log:
"{error_msg}"

Context:
{context}

Provide a root cause analysis and a specific, actionable fix.
Return your response in strict JSON format with exactly these keys:
- "root_cause": A concise explanation of why the error occurred.
- "suggested_fix": A specific command or configuration change to fix it.
- "confidence_score": A number between 0.0 and 1.0 indicating your confidence.

Do not include any markdown formatting or explanation outside the JSON."""

    print(f"[ai-engine] Calling Claude ({CLAUDE_MODEL})...")

    try:
        message = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        content = message.content[0].text
        print(f"[ai-engine] Claude response (first 300 chars): {content[:300]}")

        try:
            analysis = json.loads(clean_json_response(content))
            return {
                "root_cause":       analysis.get("root_cause",       "Analysis failed to extract root cause."),
                "suggested_fix":    analysis.get("suggested_fix",    "Analysis failed to extract fix."),
                "confidence_score": float(analysis.get("confidence_score", 0.5)),
            }
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[ai-engine] Failed to parse Claude response: {e}\nRaw: {content}")
            return {
                "root_cause":       "AI Analysis failed to parse response.",
                "suggested_fix":    "Check logs manually.",
                "confidence_score": 0.0,
            }

    except anthropic.APIConnectionError as e:
        print(f"[ai-engine] Claude API connection error: {e}")
        return {
            "root_cause":       "AI Service Unavailable (Claude API connection failed).",
            "suggested_fix":    "Check ANTHROPIC_API_KEY and network connectivity.",
            "confidence_score": 0.0,
        }
    except anthropic.AuthenticationError as e:
        print(f"[ai-engine] Claude API auth error: {e}")
        return {
            "root_cause":       "AI Service Unavailable (invalid or missing ANTHROPIC_API_KEY).",
            "suggested_fix":    "Set a valid ANTHROPIC_API_KEY environment variable.",
            "confidence_score": 0.0,
        }
    except anthropic.APIError as e:
        print(f"[ai-engine] Claude API error: {e}")
        return {
            "root_cause":       f"AI Service Unavailable (Claude API error: {type(e).__name__}).",
            "suggested_fix":    "Retry the request or check the Anthropic status page.",
            "confidence_score": 0.0,
        }


@app.get("/health")
def health():
    return {"status": "ok", "model": CLAUDE_MODEL}
