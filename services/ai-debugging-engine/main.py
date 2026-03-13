import json
import os
import re

import anthropic
from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import create_engine, text as sql_text
from sqlalchemy.orm import sessionmaker

from embedder import embed as compute_embedding
from rag_pipeline import build_debug_prompt

app = FastAPI(title="AI Debugging Engine", version="0.2.0")

# Claude model — Haiku is cheapest/fastest; override via env var
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# Instantiated once at startup; reads ANTHROPIC_API_KEY from environment
_client = anthropic.Anthropic()

# pgvector retrieval — DATABASE_URL must be set for /retrieve to work
_DB_URL = os.getenv("DATABASE_URL", "")
_db_engine  = None
_DBSession  = None
if _DB_URL:
    try:
        _db_engine = create_engine(_DB_URL)
        _DBSession  = sessionmaker(bind=_db_engine)
        print(f"[ai-engine] Connected to DB for pgvector retrieval")
    except Exception as e:
        print(f"[ai-engine] DB connection failed (retrieval disabled): {e}")


# ── Schemas ────────────────────────────────────────────────────────────────────

class ErrorAnalysisRequest(BaseModel):
    error_message:     str
    pipeline_context:  str | None = None
    similar_incidents: list[str] | None = None   # from errors KNN (past failures)
    runbook_sections:  list[str] | None = None   # from runbook_chunks KNN (internal docs)


class ErrorAnalysisResponse(BaseModel):
    root_cause:       str
    suggested_fix:    str
    confidence_score: float


class EmbedRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    embedding: list[float] | None


class RetrieveRequest(BaseModel):
    embedding:    list[float]
    workspace_id: str
    k:            int = 5


class SimilarIncident(BaseModel):
    error_type:  str
    root_cause:  str
    fix:         str
    similarity:  float


class RunbookSection(BaseModel):
    """A retrieved runbook chunk returned by /retrieve."""
    source_file:   str
    section_title: str | None
    chunk_text:    str
    similarity:    float


class RetrieveResponse(BaseModel):
    incidents:        list[SimilarIncident]
    runbook_sections: list[RunbookSection]   # NEW — dual-source RAG


# ── Helpers ────────────────────────────────────────────────────────────────────

def clean_json_response(text: str) -> str:
    """Strip markdown fences so the response can be parsed as JSON."""
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*",     "", text)
    return text.strip()


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "model": CLAUDE_MODEL}


@app.post("/embed", response_model=EmbedResponse)
def embed_text(request: EmbedRequest):
    """
    Generate a 384-dim embedding vector for the given text using sentence-transformers.
    Returns null embedding on failure — caller should handle gracefully.
    """
    vec = compute_embedding(request.text)
    return {"embedding": vec}


@app.post("/retrieve", response_model=RetrieveResponse)
def retrieve_similar(request: RetrieveRequest):
    """
    KNN search via pgvector cosine distance, scoped to the caller's workspace.
    Returns up to K similar past errors with their root causes and fixes.
    Returns an empty list if pgvector is unavailable or no similar errors exist.
    """
    if _DBSession is None:
        return {"incidents": []}

    # Format vector as a PostgreSQL literal: '[0.1, 0.2, ...]'
    vec_literal = "[" + ",".join(str(v) for v in request.embedding) + "]"

    try:
        with _DBSession() as session:
            # ── Source 1: similar past error incidents ─────────────────────────
            incident_rows = session.execute(sql_text("""
                SELECT error_type, root_cause, fix,
                       1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                FROM errors
                WHERE workspace_id = :ws
                  AND embedding IS NOT NULL
                  AND root_cause IS NOT NULL
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :k
            """), {"vec": vec_literal, "ws": request.workspace_id, "k": request.k}).fetchall()

            # ── Source 2: relevant runbook sections ────────────────────────────
            runbook_rows = session.execute(sql_text("""
                SELECT source_file, section_title, chunk_text,
                       1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                FROM runbook_chunks
                WHERE workspace_id = :ws
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :k
            """), {"vec": vec_literal, "ws": request.workspace_id, "k": request.k}).fetchall()

        return {
            "incidents": [
                {
                    "error_type": r.error_type,
                    "root_cause": r.root_cause,
                    "fix":        r.fix,
                    "similarity": float(r.similarity),
                }
                for r in incident_rows
            ],
            "runbook_sections": [
                {
                    "source_file":   r.source_file,
                    "section_title": r.section_title,
                    "chunk_text":    r.chunk_text,
                    "similarity":    float(r.similarity),
                }
                for r in runbook_rows
            ],
        }
    except Exception as e:
        print(f"[ai-engine] pgvector retrieve failed: {e}")
        return {"incidents": [], "runbook_sections": []}


@app.post("/analyze", response_model=ErrorAnalysisResponse)
def analyze_error(request: ErrorAnalysisRequest):
    """
    Analyse a pipeline error using Claude and return a structured root cause + fix.

    If similar_incidents are provided (from pgvector RAG), uses a retrieval-augmented
    prompt that grounds Claude's reasoning in past resolved failures.
    Otherwise falls back to the standard SRE analyst prompt.
    """
    error_msg = request.error_message
    context   = request.pipeline_context or "No additional context provided."
    incidents = [i for i in (request.similar_incidents or []) if i]
    runbooks  = [r for r in (request.runbook_sections  or []) if r]

    if incidents or runbooks:
        # RAG path — build_debug_prompt includes JSON output instruction
        prompt = build_debug_prompt(
            error_summary=f"{error_msg}\n\nContext: {context}",
            similar_incidents=incidents,
            runbook_sections=runbooks,
        )
        print(f"[ai-engine] Using RAG prompt — {len(incidents)} incident(s), {len(runbooks)} runbook section(s)")
    else:
        # Standard path — no historical context available
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
        print(f"[ai-engine] Using standard prompt (no RAG context)")

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
