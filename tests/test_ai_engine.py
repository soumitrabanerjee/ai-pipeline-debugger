import json
import sys
import os
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "ai-debugging-engine"))

# Patch anthropic.Anthropic before importing main so the client is mocked at module load
with patch("anthropic.Anthropic"):
    from main import app

from fastapi.testclient import TestClient
client = TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_claude(text: str):
    """Return a context manager that makes _client.messages.create() return `text`."""
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = msg
    return patch("main._client", mock_client)


GOOD_ANALYSIS = json.dumps({
    "root_cause":       "Spark executor ran out of memory due to large shuffle partition.",
    "suggested_fix":    "Increase spark.executor.memory to 8g.",
    "confidence_score": 0.95,
})


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealthEndpoint:

    def test_health_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self):
        response = client.get("/health")
        assert response.json()["status"] == "ok"


# ── /analyze ──────────────────────────────────────────────────────────────────

class TestAnalyzeEndpoint:

    def test_successful_analysis(self):
        with _mock_claude(GOOD_ANALYSIS):
            response = client.post("/analyze", json={
                "error_message": "ExecutorLostFailure: Spark executor ran out of memory"
            })
        assert response.status_code == 200
        data = response.json()
        assert "root_cause" in data
        assert "suggested_fix" in data
        assert "confidence_score" in data

    def test_confidence_score_is_float(self):
        with _mock_claude(GOOD_ANALYSIS):
            response = client.post("/analyze", json={"error_message": "some error"})
        assert isinstance(response.json()["confidence_score"], float)

    def test_with_pipeline_context(self):
        with _mock_claude(GOOD_ANALYSIS):
            response = client.post("/analyze", json={
                "error_message": "OOM error",
                "pipeline_context": "Spark ETL job running daily",
            })
        assert response.status_code == 200

    def test_api_connection_error_returns_fallback(self):
        import anthropic as _anthropic
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _anthropic.APIConnectionError(request=MagicMock())
        with patch("main._client", mock_client):
            response = client.post("/analyze", json={"error_message": "some error"})
        assert response.status_code == 200
        data = response.json()
        assert "Unavailable" in data["root_cause"]
        assert data["confidence_score"] == 0.0

    def test_invalid_json_from_claude_returns_fallback(self):
        with _mock_claude("not valid json {{{{"):
            response = client.post("/analyze", json={"error_message": "some error"})
        assert response.status_code == 200
        assert response.json()["confidence_score"] == 0.0

    def test_claude_response_with_markdown_fences_is_cleaned(self):
        wrapped = "```json\n" + json.dumps({
            "root_cause":       "disk full",
            "suggested_fix":    "clear disk",
            "confidence_score": 0.8,
        }) + "\n```"
        with _mock_claude(wrapped):
            response = client.post("/analyze", json={"error_message": "disk error"})
        assert response.status_code == 200
        assert response.json()["root_cause"] == "disk full"

    def test_missing_error_message_returns_422(self):
        response = client.post("/analyze", json={})
        assert response.status_code == 422

    def test_partial_claude_response_uses_defaults(self):
        partial = json.dumps({"root_cause": "only this field"})
        with _mock_claude(partial):
            response = client.post("/analyze", json={"error_message": "error"})
        assert response.status_code == 200
        data = response.json()
        assert data["root_cause"] == "only this field"
        assert data["suggested_fix"] != ""
        assert data["confidence_score"] == 0.5
