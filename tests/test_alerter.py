"""
Tests for the Slack alerting service.

All HTTP calls are mocked — no real Slack webhook is hit.
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.alerting.alerter import send_slack_alert, build_slack_payload


SAMPLE = dict(
    pipeline_name="customer_etl",
    run_id="run_001",
    error_type="ExecutorLostFailure",
    root_cause="Spark executor memory exceeded",
    fix="Increase spark.executor.memory to 8g",
)


# ── build_slack_payload ────────────────────────────────────────────────────────

class TestBuildSlackPayload:

    def test_returns_dict(self):
        payload = build_slack_payload(**SAMPLE)
        assert isinstance(payload, dict)

    def test_text_contains_pipeline_name(self):
        payload = build_slack_payload(**SAMPLE)
        assert "customer_etl" in payload["text"]

    def test_blocks_present(self):
        payload = build_slack_payload(**SAMPLE)
        assert "blocks" in payload
        assert len(payload["blocks"]) > 0

    def test_header_block_contains_pipeline_name(self):
        payload = build_slack_payload(**SAMPLE)
        header = payload["blocks"][0]
        assert header["type"] == "header"
        assert "customer_etl" in header["text"]["text"]

    def test_run_id_in_payload(self):
        payload = build_slack_payload(**SAMPLE)
        payload_str = str(payload)
        assert "run_001" in payload_str

    def test_error_type_in_payload(self):
        payload = build_slack_payload(**SAMPLE)
        payload_str = str(payload)
        assert "ExecutorLostFailure" in payload_str

    def test_root_cause_in_payload(self):
        payload = build_slack_payload(**SAMPLE)
        payload_str = str(payload)
        assert "Spark executor memory exceeded" in payload_str

    def test_fix_in_payload(self):
        payload = build_slack_payload(**SAMPLE)
        payload_str = str(payload)
        assert "Increase spark.executor.memory" in payload_str


# ── send_slack_alert ───────────────────────────────────────────────────────────

class TestSendSlackAlert:

    def test_returns_false_when_no_webhook_url(self):
        result = send_slack_alert(**SAMPLE, webhook_url="")
        assert result is False

    def test_no_http_call_when_no_webhook_url(self):
        with patch("services.alerting.alerter.requests.post") as mock_post:
            send_slack_alert(**SAMPLE, webhook_url="")
            mock_post.assert_not_called()

    def test_returns_true_on_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("services.alerting.alerter.requests.post", return_value=mock_resp):
            result = send_slack_alert(**SAMPLE, webhook_url="https://hooks.slack.com/test")
        assert result is True

    def test_returns_false_on_non_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "invalid_payload"
        with patch("services.alerting.alerter.requests.post", return_value=mock_resp):
            result = send_slack_alert(**SAMPLE, webhook_url="https://hooks.slack.com/test")
        assert result is False

    def test_posts_to_correct_url(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        url = "https://hooks.slack.com/services/T000/B000/xxxx"
        with patch("services.alerting.alerter.requests.post", return_value=mock_resp) as mock_post:
            send_slack_alert(**SAMPLE, webhook_url=url)
            called_url = mock_post.call_args[0][0]
        assert called_url == url

    def test_returns_false_on_connection_error(self):
        import requests as req
        with patch("services.alerting.alerter.requests.post",
                   side_effect=req.exceptions.ConnectionError("refused")):
            result = send_slack_alert(**SAMPLE, webhook_url="https://hooks.slack.com/test")
        assert result is False

    def test_returns_false_on_timeout(self):
        import requests as req
        with patch("services.alerting.alerter.requests.post",
                   side_effect=req.exceptions.Timeout()):
            result = send_slack_alert(**SAMPLE, webhook_url="https://hooks.slack.com/test")
        assert result is False

    def test_uses_env_webhook_when_no_override(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        env_url = "https://hooks.slack.com/env-url"
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": env_url}):
            # Reload module-level constant via monkeypatching the module attribute
            with patch("services.alerting.alerter.SLACK_WEBHOOK_URL", env_url):
                with patch("services.alerting.alerter.requests.post",
                           return_value=mock_resp) as mock_post:
                    send_slack_alert(**SAMPLE)
                    called_url = mock_post.call_args[0][0]
        assert called_url == env_url
