import json
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "ai-debugging-engine"))
from main import app

client = TestClient(app)

MOCK_OLLAMA_SUCCESS = {
    "response": json.dumps({
        "root_cause": "Spark executor ran out of memory due to large shuffle partition.",
        "suggested_fix": "Increase spark.executor.memory to 8g.",
        "confidence_score": 0.95
    })
}


def make_mock_response(body: dict, status_code: int = 200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = json.dumps(body)
    mock.json.return_value = body
    mock.raise_for_status = MagicMock()
    return mock


class TestHealthEndpoint:

    def test_health_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self):
        response = client.get("/health")
        assert response.json() == {"status": "ok"}


class TestAnalyzeEndpoint:

    def test_successful_analysis(self):
        with patch("requests.post", return_value=make_mock_response(MOCK_OLLAMA_SUCCESS)):
            response = client.post("/analyze", json={
                "error_message": "ExecutorLostFailure: Spark executor ran out of memory"
            })
        assert response.status_code == 200
        data = response.json()
        assert "root_cause" in data
        assert "suggested_fix" in data
        assert "confidence_score" in data

    def test_confidence_score_is_float(self):
        with patch("requests.post", return_value=make_mock_response(MOCK_OLLAMA_SUCCESS)):
            response = client.post("/analyze", json={"error_message": "some error"})
        assert isinstance(response.json()["confidence_score"], float)

    def test_with_pipeline_context(self):
        with patch("requests.post", return_value=make_mock_response(MOCK_OLLAMA_SUCCESS)):
            response = client.post("/analyze", json={
                "error_message": "OOM error",
                "pipeline_context": "Spark ETL job running daily"
            })
        assert response.status_code == 200

    def test_ollama_connection_failure_returns_fallback(self):
        import requests as req
        with patch("requests.post", side_effect=req.RequestException("connection refused")):
            response = client.post("/analyze", json={"error_message": "some error"})
        assert response.status_code == 200
        data = response.json()
        assert "Ollama" in data["root_cause"] or "Unavailable" in data["root_cause"]
        assert data["confidence_score"] == 0.0

    def test_invalid_json_from_ollama_returns_fallback(self):
        bad_response = {"response": "not valid json {{{{"}
        with patch("requests.post", return_value=make_mock_response(bad_response)):
            response = client.post("/analyze", json={"error_message": "some error"})
        assert response.status_code == 200
        assert response.json()["confidence_score"] == 0.0

    def test_ollama_response_with_markdown_fences_is_cleaned(self):
        wrapped = {"response": "```json\n" + json.dumps({
            "root_cause": "disk full",
            "suggested_fix": "clear disk",
            "confidence_score": 0.8
        }) + "\n```"}
        with patch("requests.post", return_value=make_mock_response(wrapped)):
            response = client.post("/analyze", json={"error_message": "disk error"})
        assert response.status_code == 200
        assert response.json()["root_cause"] == "disk full"

    def test_missing_error_message_returns_422(self):
        response = client.post("/analyze", json={})
        assert response.status_code == 422

    def test_partial_ollama_response_uses_defaults(self):
        partial = {"response": json.dumps({"root_cause": "only this field"})}
        with patch("requests.post", return_value=make_mock_response(partial)):
            response = client.post("/analyze", json={"error_message": "error"})
        assert response.status_code == 200
        data = response.json()
        assert data["root_cause"] == "only this field"
        assert data["suggested_fix"] != ""
        assert data["confidence_score"] == 0.5
