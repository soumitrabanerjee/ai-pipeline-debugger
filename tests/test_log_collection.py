"""
Tests for the Log Collection Layer:
  - log_parser.py  (parse_log_line, build_ingest_payload)
  - agent.py       (send_to_ingest, LogDirectoryHandler, scan_existing)
  - webhook_collector.py (FastAPI endpoints)

No real files, network calls, or watchdog observers are used.
"""

import sys
import os
import uuid
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

_LAYER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "services", "log-collection-layer"))
sys.path.insert(0, _LAYER)

from log_parser import parse_log_line, build_ingest_payload, ParsedLine
from agent import LogDirectoryHandler, send_to_ingest, scan_existing, _FileTailer
import webhook_collector
from webhook_collector import app as webhook_app, _validate_api_key

# Bypass DB validation in unit tests — API key auth is covered by test_api_keys.py
def _mock_validate_api_key():
    return "dpd_test_key"

webhook_app.dependency_overrides[_validate_api_key] = _mock_validate_api_key

webhook_client = TestClient(webhook_app)
_API_KEY_HDR = {"x-api-key": "dpd_test_key"}


# ══════════════════════════════════════════════════════════════════════════════
# log_parser — parse_log_line
# ══════════════════════════════════════════════════════════════════════════════

class TestParseLogLine:

    def test_returns_none_for_empty_line(self):
        assert parse_log_line("") is None

    def test_returns_none_for_unrecognised_format(self):
        assert parse_log_line("just some random text with no timestamp") is None

    # Spark format
    def test_parses_spark_error_line(self):
        line = "2026-03-08T10:23:45.000Z ERROR ExecutorLostFailure: executor ran out of memory"
        result = parse_log_line(line)
        assert result is not None
        assert result.level == "ERROR"
        assert result.source_format == "spark"

    def test_parses_spark_info_line(self):
        line = "2026-03-08T10:23:45.000Z INFO SparkContext: Running Spark version 3.5.0"
        result = parse_log_line(line)
        assert result is not None
        assert result.level == "INFO"

    def test_spark_message_extracted_correctly(self):
        line = "2026-03-08T10:23:45.000Z ERROR ExecutorLostFailure: executor died"
        result = parse_log_line(line)
        assert "ExecutorLostFailure" in result.message

    # Airflow format
    def test_parses_airflow_error_line(self):
        line = "[2026-03-08 10:23:45,123] {taskinstance.py:1234} ERROR - Task failed with OOM"
        result = parse_log_line(line)
        assert result is not None
        assert result.level == "ERROR"
        assert result.source_format == "airflow"

    def test_parses_airflow_info_line(self):
        line = "[2026-03-08 10:23:45,123] {taskinstance.py:100} INFO - Starting attempt 1 of 1"
        result = parse_log_line(line)
        assert result is not None
        assert result.level == "INFO"

    def test_airflow_message_extracted_correctly(self):
        line = "[2026-03-08 10:23:45,123] {taskinstance.py:1234} ERROR - AirflowException: bad dag"
        result = parse_log_line(line)
        assert "AirflowException" in result.message

    def test_warning_normalised_to_warn(self):
        line = "2026-03-08T10:23:45.000Z WARNING low disk space on executor"
        result = parse_log_line(line)
        assert result is not None
        assert result.level == "WARN"

    def test_timestamp_normalised_to_iso(self):
        line = "2026-03-08T10:23:45.000Z ERROR some error"
        result = parse_log_line(line)
        assert result.timestamp.endswith("Z")
        assert "2026-03-08" in result.timestamp

    def test_raw_line_preserved(self):
        line = "2026-03-08T10:23:45.000Z ERROR raw line"
        result = parse_log_line(line)
        assert result.raw == line


# ══════════════════════════════════════════════════════════════════════════════
# log_parser — build_ingest_payload
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildIngestPayload:

    def _parsed(self, level="ERROR", message="OOM error", ts="2026-03-08T10:00:00Z", fmt="spark"):
        return ParsedLine(level=level, message=message, timestamp=ts, source_format=fmt, raw="")

    def test_payload_has_all_required_fields(self):
        payload = build_ingest_payload(self._parsed(), job_id="my-pipeline")
        for key in ("source", "workspace_id", "job_id", "run_id", "level", "timestamp", "message"):
            assert key in payload

    def test_job_id_is_set(self):
        payload = build_ingest_payload(self._parsed(), job_id="spark-etl")
        assert payload["job_id"] == "spark-etl"

    def test_level_is_preserved(self):
        payload = build_ingest_payload(self._parsed(level="ERROR"), job_id="p")
        assert payload["level"] == "ERROR"

    def test_message_is_preserved(self):
        payload = build_ingest_payload(self._parsed(message="heap OOM"), job_id="p")
        assert payload["message"] == "heap OOM"

    def test_timestamp_is_preserved(self):
        payload = build_ingest_payload(self._parsed(ts="2026-03-08T12:00:00Z"), job_id="p")
        assert payload["timestamp"] == "2026-03-08T12:00:00Z"

    def test_run_id_is_a_uuid(self):
        payload = build_ingest_payload(self._parsed(), job_id="p")
        parsed_uuid = uuid.UUID(payload["run_id"])  # raises if not valid UUID
        assert str(parsed_uuid) == payload["run_id"]

    def test_each_call_generates_unique_run_id(self):
        p = self._parsed()
        ids = {build_ingest_payload(p, job_id="p")["run_id"] for _ in range(5)}
        assert len(ids) == 5

    def test_source_defaults_to_agent(self):
        payload = build_ingest_payload(self._parsed(), job_id="p")
        assert payload["source"] == "agent"

    def test_custom_source_is_used(self):
        payload = build_ingest_payload(self._parsed(), job_id="p", source="spark-cluster")
        assert payload["source"] == "spark-cluster"


# ══════════════════════════════════════════════════════════════════════════════
# agent — send_to_ingest
# ══════════════════════════════════════════════════════════════════════════════

class TestSendToIngest:

    def _payload(self):
        return {"job_id": "test", "level": "ERROR", "message": "OOM"}

    def test_returns_true_on_202(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        with patch("agent.requests.post", return_value=mock_resp):
            assert send_to_ingest(self._payload()) is True

    def test_returns_true_on_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("agent.requests.post", return_value=mock_resp):
            assert send_to_ingest(self._payload()) is True

    def test_returns_false_on_500(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("agent.requests.post", return_value=mock_resp):
            assert send_to_ingest(self._payload()) is False

    def test_returns_false_on_connection_error(self):
        import requests as req
        with patch("agent.requests.post",
                   side_effect=req.exceptions.ConnectionError()):
            assert send_to_ingest(self._payload()) is False

    def test_posts_to_correct_url(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        url = "http://ingest:8000/ingest"
        with patch("agent.requests.post",
                   return_value=mock_resp) as mock_post:
            send_to_ingest(self._payload(), ingest_url=url)
            assert mock_post.call_args[0][0] == url


# ══════════════════════════════════════════════════════════════════════════════
# agent — FileTailer
# ══════════════════════════════════════════════════════════════════════════════

class TestFileTailer:

    def test_reads_new_lines_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("line one\nline two\n")
            path = f.name
        try:
            tailer = _FileTailer(path)
            lines = tailer.read_new_lines()
            assert "line one\n" in lines
            assert "line two\n" in lines
        finally:
            os.unlink(path)

    def test_does_not_reread_old_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("old line\n")
            path = f.name
        try:
            tailer = _FileTailer(path)
            tailer.read_new_lines()  # consume

            with open(path, "a") as fh:
                fh.write("new line\n")

            lines = tailer.read_new_lines()
            assert lines == ["new line\n"]
        finally:
            os.unlink(path)

    def test_returns_empty_for_nonexistent_file(self):
        tailer = _FileTailer("/nonexistent/path/file.log")
        assert tailer.read_new_lines() == []


# ══════════════════════════════════════════════════════════════════════════════
# agent — LogDirectoryHandler (unit — no real filesystem events)
# ══════════════════════════════════════════════════════════════════════════════

class TestLogDirectoryHandler:

    def test_only_forwards_error_lines(self):
        handler = LogDirectoryHandler(job_id="test-pipeline", ingest_url="http://x/ingest")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("2026-03-08T10:00:00Z INFO just an info line\n")
            f.write("2026-03-08T10:00:01Z ERROR ExecutorLostFailure: OOM\n")
            path = f.name
        try:
            with patch("agent.send_to_ingest",
                       return_value=True) as mock_send:
                handler._process_file(path)
            assert mock_send.call_count == 1
            payload = mock_send.call_args[0][0]
            assert payload["level"] == "ERROR"
        finally:
            os.unlink(path)

    def test_skips_non_log_files(self):
        handler = LogDirectoryHandler(job_id="test-pipeline")
        with patch("agent.send_to_ingest") as mock_send:
            handler._process_file("/tmp/some_file.csv")
        mock_send.assert_not_called()

    def test_job_id_in_forwarded_payload(self):
        handler = LogDirectoryHandler(job_id="my-etl-job")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("2026-03-08T10:00:00Z ERROR SchemaMismatch: column missing\n")
            path = f.name
        try:
            with patch("agent.send_to_ingest",
                       return_value=True) as mock_send:
                handler._process_file(path)
            payload = mock_send.call_args[0][0]
            assert payload["job_id"] == "my-etl-job"
        finally:
            os.unlink(path)

    def test_scan_existing_processes_log_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "spark.log")
            with open(log_path, "w") as f:
                f.write("2026-03-08T10:00:00Z ERROR OOM error happened\n")

            handler = LogDirectoryHandler(job_id="scan-test")
            with patch("agent.send_to_ingest",
                       return_value=True) as mock_send:
                scan_existing(tmp, handler)
            assert mock_send.call_count == 1


# ══════════════════════════════════════════════════════════════════════════════
# webhook_collector endpoints
# ══════════════════════════════════════════════════════════════════════════════

class TestWebhookCollectorHealth:

    def test_health_returns_200(self):
        assert webhook_client.get("/health").status_code == 200

    def test_health_body(self):
        assert webhook_client.get("/health").json() == {"status": "ok"}


class TestAirflowWebhook:

    _BODY = {
        "dag_id": "customer_etl",
        "run_id": "run_2026_03_08",
        "task_id": "extract_data",
        "exception": "AirflowException: upstream sensor timed out",
        "log_url": "http://airflow/log/1",
    }

    def test_returns_202(self):
        with patch("webhook_collector._forward"):
            resp = webhook_client.post("/webhook/airflow", json=self._BODY, headers=_API_KEY_HDR)
        assert resp.status_code == 202

    def test_returns_run_id(self):
        with patch("webhook_collector._forward"):
            resp = webhook_client.post("/webhook/airflow", json=self._BODY, headers=_API_KEY_HDR)
        assert resp.json()["run_id"] == self._BODY["run_id"]

    def test_missing_required_fields_returns_422(self):
        resp = webhook_client.post("/webhook/airflow", json={"dag_id": "x"})
        assert resp.status_code == 422

    def test_forwarded_payload_has_correct_source(self):
        captured = {}
        def fake_forward(payload, api_key):
            captured.update(payload)
        with patch("webhook_collector._forward", side_effect=fake_forward):
            webhook_client.post("/webhook/airflow", json=self._BODY, headers=_API_KEY_HDR)
        assert captured["source"] == "airflow"

    def test_forwarded_payload_maps_dag_id_to_job_id(self):
        captured = {}
        def fake_forward(payload, api_key):
            captured.update(payload)
        with patch("webhook_collector._forward", side_effect=fake_forward):
            webhook_client.post("/webhook/airflow", json=self._BODY, headers=_API_KEY_HDR)
        assert captured["job_id"] == "customer_etl"

    def test_forwarded_payload_level_is_error(self):
        captured = {}
        def fake_forward(payload, api_key):
            captured.update(payload)
        with patch("webhook_collector._forward", side_effect=fake_forward):
            webhook_client.post("/webhook/airflow", json=self._BODY, headers=_API_KEY_HDR)
        assert captured["level"] == "ERROR"


class TestGenericWebhook:

    _BODY = {
        "pipeline": "billing-etl",
        "level": "ERROR",
        "message": "NullPointerException in transform stage",
    }

    def test_returns_202(self):
        with patch("webhook_collector._forward"):
            resp = webhook_client.post("/webhook/generic", json=self._BODY, headers=_API_KEY_HDR)
        assert resp.status_code == 202

    def test_generates_run_id_when_not_provided(self):
        with patch("webhook_collector._forward"):
            resp = webhook_client.post("/webhook/generic", json=self._BODY, headers=_API_KEY_HDR)
        run_id = resp.json()["run_id"]
        uuid.UUID(run_id)  # raises if not a valid UUID

    def test_uses_provided_run_id(self):
        body = {**self._BODY, "run_id": "my-custom-run-id"}
        with patch("webhook_collector._forward"):
            resp = webhook_client.post("/webhook/generic", json=body, headers=_API_KEY_HDR)
        assert resp.json()["run_id"] == "my-custom-run-id"

    def test_forwarded_payload_has_pipeline_as_job_id(self):
        captured = {}
        def fake_forward(payload, api_key):
            captured.update(payload)
        with patch("webhook_collector._forward", side_effect=fake_forward):
            webhook_client.post("/webhook/generic", json=self._BODY, headers=_API_KEY_HDR)
        assert captured["job_id"] == "billing-etl"

    def test_level_upcased(self):
        body = {**self._BODY, "level": "error"}
        captured = {}
        def fake_forward(payload, api_key):
            captured.update(payload)
        with patch("webhook_collector._forward", side_effect=fake_forward):
            webhook_client.post("/webhook/generic", json=body, headers=_API_KEY_HDR)
        assert captured["level"] == "ERROR"

    def test_missing_pipeline_returns_422(self):
        resp = webhook_client.post("/webhook/generic", json={"message": "oops"})
        assert resp.status_code == 422
