"""
Tests for the multi-channel alerting service.

All outbound HTTP calls and SMTP connections are mocked — no real services hit.

Channels tested:
  Slack      — build_slack_payload, send_slack_alert
  Teams      — build_teams_payload, send_teams_alert
  Email      — build_email_message, send_email_alert
  PagerDuty  — build_pagerduty_payload, send_pagerduty_alert
  Dispatcher — send_alerts (fires all channels)
"""

import sys
import os
import smtplib
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.alerting.alerter import (
    build_slack_payload,
    send_slack_alert,
    build_teams_payload,
    send_teams_alert,
    build_email_message,
    send_email_alert,
    build_pagerduty_payload,
    send_pagerduty_alert,
    send_alerts,
    _truncate,
)


SAMPLE = dict(
    pipeline_name="customer_etl",
    run_id="run_001",
    error_type="ExecutorLostFailure",
    root_cause="Spark executor memory exceeded",
    fix="Increase spark.executor.memory to 8g",
)


# ── _truncate helper ───────────────────────────────────────────────────────────

class TestTruncate:
    def test_short_string_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_exact_limit_unchanged(self):
        assert _truncate("hello", 5) == "hello"

    def test_long_string_truncated(self):
        result = _truncate("hello world", 7)
        assert len(result) == 7
        assert result.endswith("…")

    def test_empty_string(self):
        assert _truncate("", 10) == ""


# ── Slack: build_slack_payload ─────────────────────────────────────────────────

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
        assert "run_001" in str(build_slack_payload(**SAMPLE))

    def test_error_type_in_payload(self):
        assert "ExecutorLostFailure" in str(build_slack_payload(**SAMPLE))

    def test_root_cause_in_payload(self):
        assert "Spark executor memory exceeded" in str(build_slack_payload(**SAMPLE))

    def test_fix_in_payload(self):
        assert "Increase spark.executor.memory" in str(build_slack_payload(**SAMPLE))

    def test_critical_severity_uses_alarm_emoji(self):
        payload = build_slack_payload(**SAMPLE, severity="CRITICAL")
        assert "🚨" in payload["text"]

    def test_warn_severity_uses_warning_emoji(self):
        payload = build_slack_payload(**SAMPLE, severity="WARN")
        assert "⚠️" in payload["text"]

    def test_dashboard_url_override(self):
        payload = build_slack_payload(**SAMPLE, dashboard_url="https://my.dash/")
        assert "https://my.dash/" in str(payload)

    def test_long_run_id_truncated(self):
        long_id = "r" * 60
        payload = build_slack_payload(**{**SAMPLE, "run_id": long_id})
        # Should be truncated with ellipsis
        assert "…" in str(payload)


# ── Slack: send_slack_alert ────────────────────────────────────────────────────

class TestSendSlackAlert:

    def test_returns_false_when_no_webhook_url(self):
        assert send_slack_alert(**SAMPLE, webhook_url="") is False

    def test_no_http_call_when_no_webhook_url(self):
        with patch("services.alerting.alerter.requests.post") as mock_post:
            send_slack_alert(**SAMPLE, webhook_url="")
            mock_post.assert_not_called()

    def test_returns_true_on_200(self):
        mock_resp = MagicMock(status_code=200)
        with patch("services.alerting.alerter.requests.post", return_value=mock_resp):
            assert send_slack_alert(**SAMPLE, webhook_url="https://hooks.slack.com/x") is True

    def test_returns_false_on_non_200(self):
        mock_resp = MagicMock(status_code=400, text="invalid_payload")
        with patch("services.alerting.alerter.requests.post", return_value=mock_resp):
            assert send_slack_alert(**SAMPLE, webhook_url="https://hooks.slack.com/x") is False

    def test_posts_to_correct_url(self):
        mock_resp = MagicMock(status_code=200)
        url = "https://hooks.slack.com/services/T000/B000/xxxx"
        with patch("services.alerting.alerter.requests.post", return_value=mock_resp) as mock_post:
            send_slack_alert(**SAMPLE, webhook_url=url)
        assert mock_post.call_args[0][0] == url

    def test_returns_false_on_connection_error(self):
        import requests as req
        with patch("services.alerting.alerter.requests.post",
                   side_effect=req.exceptions.ConnectionError("refused")):
            assert send_slack_alert(**SAMPLE, webhook_url="https://hooks.slack.com/x") is False

    def test_returns_false_on_timeout(self):
        import requests as req
        with patch("services.alerting.alerter.requests.post",
                   side_effect=req.exceptions.Timeout()):
            assert send_slack_alert(**SAMPLE, webhook_url="https://hooks.slack.com/x") is False

    def test_uses_env_webhook_when_no_override(self):
        mock_resp = MagicMock(status_code=200)
        env_url = "https://hooks.slack.com/env-url"
        with patch("services.alerting.alerter.SLACK_WEBHOOK_URL", env_url):
            with patch("services.alerting.alerter.requests.post",
                       return_value=mock_resp) as mock_post:
                send_slack_alert(**SAMPLE)
        assert mock_post.call_args[0][0] == env_url


# ── Teams: build_teams_payload ─────────────────────────────────────────────────

class TestBuildTeamsPayload:

    def test_returns_dict(self):
        assert isinstance(build_teams_payload(**SAMPLE), dict)

    def test_type_is_message_card(self):
        payload = build_teams_payload(**SAMPLE)
        assert payload["@type"] == "MessageCard"

    def test_summary_contains_pipeline_name(self):
        payload = build_teams_payload(**SAMPLE)
        assert "customer_etl" in payload["summary"]

    def test_sections_present(self):
        payload = build_teams_payload(**SAMPLE)
        assert len(payload["sections"]) > 0

    def test_pipeline_name_in_facts(self):
        payload = build_teams_payload(**SAMPLE)
        facts = payload["sections"][0]["facts"]
        names = [f["name"] for f in facts]
        assert "Pipeline" in names

    def test_error_type_in_sections(self):
        assert "ExecutorLostFailure" in str(build_teams_payload(**SAMPLE))

    def test_root_cause_in_sections(self):
        assert "Spark executor memory exceeded" in str(build_teams_payload(**SAMPLE))

    def test_fix_in_sections(self):
        assert "Increase spark.executor.memory" in str(build_teams_payload(**SAMPLE))

    def test_critical_uses_dark_red_color(self):
        payload = build_teams_payload(**SAMPLE, severity="CRITICAL")
        assert payload["themeColor"] == "8B0000"

    def test_potential_action_has_dashboard_link(self):
        payload = build_teams_payload(**SAMPLE, dashboard_url="https://dash.example.com/")
        actions = payload["potentialAction"]
        assert any("https://dash.example.com/" in str(a) for a in actions)


# ── Teams: send_teams_alert ────────────────────────────────────────────────────

class TestSendTeamsAlert:

    def test_returns_false_when_no_webhook_url(self):
        assert send_teams_alert(**SAMPLE, webhook_url="") is False

    def test_no_http_call_when_not_configured(self):
        with patch("services.alerting.alerter.TEAMS_WEBHOOK_URL", ""):
            with patch("services.alerting.alerter.requests.post") as mock_post:
                send_teams_alert(**SAMPLE)
                mock_post.assert_not_called()

    def test_returns_true_on_200(self):
        mock_resp = MagicMock(status_code=200)
        with patch("services.alerting.alerter.requests.post", return_value=mock_resp):
            assert send_teams_alert(**SAMPLE, webhook_url="https://outlook.office.com/x") is True

    def test_returns_false_on_non_200(self):
        mock_resp = MagicMock(status_code=400, text="bad request")
        with patch("services.alerting.alerter.requests.post", return_value=mock_resp):
            assert send_teams_alert(**SAMPLE, webhook_url="https://outlook.office.com/x") is False

    def test_posts_to_correct_url(self):
        mock_resp = MagicMock(status_code=200)
        url = "https://outlook.office.com/webhook/abc"
        with patch("services.alerting.alerter.requests.post", return_value=mock_resp) as mock_post:
            send_teams_alert(**SAMPLE, webhook_url=url)
        assert mock_post.call_args[0][0] == url

    def test_returns_false_on_timeout(self):
        import requests as req
        with patch("services.alerting.alerter.requests.post",
                   side_effect=req.exceptions.Timeout()):
            assert send_teams_alert(**SAMPLE, webhook_url="https://outlook.office.com/x") is False

    def test_returns_false_on_connection_error(self):
        import requests as req
        with patch("services.alerting.alerter.requests.post",
                   side_effect=req.exceptions.ConnectionError("refused")):
            assert send_teams_alert(**SAMPLE, webhook_url="https://outlook.office.com/x") is False

    def test_uses_env_webhook_when_no_override(self):
        mock_resp = MagicMock(status_code=200)
        env_url = "https://outlook.office.com/env-url"
        with patch("services.alerting.alerter.TEAMS_WEBHOOK_URL", env_url):
            with patch("services.alerting.alerter.requests.post",
                       return_value=mock_resp) as mock_post:
                send_teams_alert(**SAMPLE)
        assert mock_post.call_args[0][0] == env_url


# ── Email: build_email_message ─────────────────────────────────────────────────

class TestBuildEmailMessage:

    def _build(self, **kwargs):
        return build_email_message(
            **SAMPLE,
            from_addr="alerts@example.com",
            to_addrs=["ops@example.com"],
            **kwargs,
        )

    def test_returns_mime_multipart(self):
        from email.mime.multipart import MIMEMultipart
        assert isinstance(self._build(), MIMEMultipart)

    def test_subject_contains_pipeline_name(self):
        msg = self._build()
        assert "customer_etl" in msg["Subject"]

    def test_subject_contains_severity(self):
        msg = self._build(severity="CRITICAL")
        assert "CRITICAL" in msg["Subject"]

    def test_from_addr_set(self):
        msg = self._build()
        assert msg["From"] == "alerts@example.com"

    def test_to_addr_set(self):
        msg = self._build()
        assert "ops@example.com" in msg["To"]

    def _html_body(self, msg):
        """Decode the base64-encoded HTML part from a MIMEMultipart message."""
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return part.get_payload(decode=True).decode("utf-8")
        return msg.as_string()

    def test_html_body_contains_pipeline_name(self):
        msg = self._build()
        assert "customer_etl" in self._html_body(msg)

    def test_html_body_contains_root_cause(self):
        msg = self._build()
        assert "Spark executor memory exceeded" in self._html_body(msg)

    def test_html_body_contains_fix(self):
        msg = self._build()
        assert "Increase spark.executor.memory" in self._html_body(msg)

    def test_html_body_contains_dashboard_link(self):
        msg = build_email_message(
            **SAMPLE,
            from_addr="alerts@example.com",
            to_addrs=["ops@example.com"],
            dashboard_url="https://dash.example.com/",
        )
        assert "https://dash.example.com/" in self._html_body(msg)

    def test_multiple_recipients_in_to_header(self):
        msg = build_email_message(
            **SAMPLE,
            from_addr="alerts@example.com",
            to_addrs=["a@example.com", "b@example.com"],
        )
        assert "a@example.com" in msg["To"]
        assert "b@example.com" in msg["To"]


# ── Email: send_email_alert ────────────────────────────────────────────────────

class TestSendEmailAlert:

    def test_returns_false_when_not_configured(self):
        result = send_email_alert(**SAMPLE, from_addr="", to_addrs=[])
        assert result is False

    def test_no_smtp_call_when_not_configured(self):
        with patch("services.alerting.alerter.smtplib.SMTP") as mock_smtp:
            send_email_alert(**SAMPLE, from_addr="", to_addrs=[])
            mock_smtp.assert_not_called()

    def test_returns_true_on_successful_send(self):
        mock_smtp_instance = MagicMock()
        with patch("services.alerting.alerter.smtplib.SMTP", return_value=mock_smtp_instance):
            result = send_email_alert(
                **SAMPLE,
                from_addr="alerts@example.com",
                to_addrs=["ops@example.com"],
                smtp_host="smtp.example.com",
                smtp_port=587,
            )
        assert result is True

    def test_sendmail_called_with_correct_addresses(self):
        mock_smtp_instance = MagicMock()
        with patch("services.alerting.alerter.smtplib.SMTP", return_value=mock_smtp_instance):
            send_email_alert(
                **SAMPLE,
                from_addr="alerts@example.com",
                to_addrs=["ops@example.com"],
                smtp_host="smtp.example.com",
                smtp_port=587,
            )
        call_args = mock_smtp_instance.sendmail.call_args
        assert call_args[0][0] == "alerts@example.com"
        assert "ops@example.com" in call_args[0][1]

    def test_uses_smtp_ssl_when_ssl_flag_set(self):
        mock_smtp_ssl = MagicMock()
        with patch("services.alerting.alerter.smtplib.SMTP_SSL", return_value=mock_smtp_ssl):
            send_email_alert(
                **SAMPLE,
                from_addr="alerts@example.com",
                to_addrs=["ops@example.com"],
                smtp_host="smtp.example.com",
                smtp_port=465,
                smtp_use_ssl=True,
            )
        mock_smtp_ssl.sendmail.assert_called_once()

    def test_returns_false_on_smtp_exception(self):
        with patch("services.alerting.alerter.smtplib.SMTP",
                   side_effect=smtplib.SMTPException("auth failed")):
            result = send_email_alert(
                **SAMPLE,
                from_addr="alerts@example.com",
                to_addrs=["ops@example.com"],
                smtp_host="smtp.example.com",
            )
        assert result is False

    def test_returns_false_on_os_error(self):
        with patch("services.alerting.alerter.smtplib.SMTP",
                   side_effect=OSError("connection refused")):
            result = send_email_alert(
                **SAMPLE,
                from_addr="alerts@example.com",
                to_addrs=["ops@example.com"],
                smtp_host="smtp.example.com",
            )
        assert result is False

    def test_login_called_when_credentials_provided(self):
        mock_smtp_instance = MagicMock()
        with patch("services.alerting.alerter.smtplib.SMTP", return_value=mock_smtp_instance):
            send_email_alert(
                **SAMPLE,
                from_addr="alerts@example.com",
                to_addrs=["ops@example.com"],
                smtp_host="smtp.example.com",
                smtp_user="user",
                smtp_password="pass",
            )
        mock_smtp_instance.login.assert_called_once_with("user", "pass")

    def test_login_not_called_without_credentials(self):
        mock_smtp_instance = MagicMock()
        with patch("services.alerting.alerter.smtplib.SMTP", return_value=mock_smtp_instance):
            send_email_alert(
                **SAMPLE,
                from_addr="alerts@example.com",
                to_addrs=["ops@example.com"],
                smtp_host="smtp.example.com",
                smtp_user="",
                smtp_password="",
            )
        mock_smtp_instance.login.assert_not_called()

    def test_env_var_recipients_parsed(self):
        """ALERT_EMAIL_TO with comma-separated addresses is parsed correctly."""
        mock_smtp_instance = MagicMock()
        with patch("services.alerting.alerter.ALERT_EMAIL_FROM", "alerts@example.com"):
            with patch("services.alerting.alerter.ALERT_EMAIL_TO", "a@x.com, b@x.com"):
                with patch("services.alerting.alerter.smtplib.SMTP",
                           return_value=mock_smtp_instance):
                    result = send_email_alert(**SAMPLE, smtp_host="smtp.example.com")
        assert result is True
        recipients = mock_smtp_instance.sendmail.call_args[0][1]
        assert len(recipients) == 2


# ── PagerDuty: build_pagerduty_payload ────────────────────────────────────────

class TestBuildPagerDutyPayload:

    def test_returns_dict(self):
        assert isinstance(build_pagerduty_payload(**SAMPLE, routing_key="rkey"), dict)

    def test_event_action_is_trigger(self):
        payload = build_pagerduty_payload(**SAMPLE, routing_key="rkey")
        assert payload["event_action"] == "trigger"

    def test_routing_key_in_payload(self):
        payload = build_pagerduty_payload(**SAMPLE, routing_key="my_routing_key")
        assert payload["routing_key"] == "my_routing_key"

    def test_summary_contains_pipeline_name(self):
        payload = build_pagerduty_payload(**SAMPLE, routing_key="rkey")
        assert "customer_etl" in payload["payload"]["summary"]

    def test_severity_critical_maps_correctly(self):
        payload = build_pagerduty_payload(**SAMPLE, severity="CRITICAL", routing_key="rkey")
        assert payload["payload"]["severity"] == "critical"

    def test_severity_error_maps_correctly(self):
        payload = build_pagerduty_payload(**SAMPLE, severity="ERROR", routing_key="rkey")
        assert payload["payload"]["severity"] == "error"

    def test_severity_warn_maps_to_warning(self):
        payload = build_pagerduty_payload(**SAMPLE, severity="WARN", routing_key="rkey")
        assert payload["payload"]["severity"] == "warning"

    def test_custom_details_has_root_cause(self):
        payload = build_pagerduty_payload(**SAMPLE, routing_key="rkey")
        details = payload["payload"]["custom_details"]
        assert "Spark executor memory exceeded" in details["root_cause"]

    def test_custom_details_has_fix(self):
        payload = build_pagerduty_payload(**SAMPLE, routing_key="rkey")
        details = payload["payload"]["custom_details"]
        assert "Increase spark.executor.memory" in details["suggested_fix"]

    def test_dedup_key_contains_pipeline_name(self):
        payload = build_pagerduty_payload(**SAMPLE, routing_key="rkey")
        assert "customer_etl" in payload["dedup_key"]


# ── PagerDuty: send_pagerduty_alert ───────────────────────────────────────────

class TestSendPagerDutyAlert:

    def test_returns_false_when_no_routing_key(self):
        assert send_pagerduty_alert(**SAMPLE, routing_key="") is False

    def test_no_http_call_when_not_configured(self):
        with patch("services.alerting.alerter.PAGERDUTY_ROUTING_KEY", ""):
            with patch("services.alerting.alerter.requests.post") as mock_post:
                send_pagerduty_alert(**SAMPLE)
                mock_post.assert_not_called()

    def test_returns_true_on_202(self):
        mock_resp = MagicMock(status_code=202)
        mock_resp.json.return_value = {"status": "success", "dedup_key": "abc"}
        with patch("services.alerting.alerter.requests.post", return_value=mock_resp):
            assert send_pagerduty_alert(**SAMPLE, routing_key="rkey") is True

    def test_returns_false_on_non_202(self):
        mock_resp = MagicMock(status_code=400, text="invalid key")
        with patch("services.alerting.alerter.requests.post", return_value=mock_resp):
            assert send_pagerduty_alert(**SAMPLE, routing_key="rkey") is False

    def test_posts_to_pagerduty_events_url(self):
        mock_resp = MagicMock(status_code=202)
        mock_resp.json.return_value = {"dedup_key": "abc"}
        with patch("services.alerting.alerter.requests.post", return_value=mock_resp) as mock_post:
            send_pagerduty_alert(**SAMPLE, routing_key="rkey")
        called_url = mock_post.call_args[0][0]
        assert "pagerduty.com" in called_url

    def test_routing_key_in_request_body(self):
        mock_resp = MagicMock(status_code=202)
        mock_resp.json.return_value = {"dedup_key": "abc"}
        with patch("services.alerting.alerter.requests.post", return_value=mock_resp) as mock_post:
            send_pagerduty_alert(**SAMPLE, routing_key="test_rkey_123")
        body = mock_post.call_args[1]["json"]
        assert body["routing_key"] == "test_rkey_123"

    def test_returns_false_on_timeout(self):
        import requests as req
        with patch("services.alerting.alerter.requests.post",
                   side_effect=req.exceptions.Timeout()):
            assert send_pagerduty_alert(**SAMPLE, routing_key="rkey") is False

    def test_returns_false_on_connection_error(self):
        import requests as req
        with patch("services.alerting.alerter.requests.post",
                   side_effect=req.exceptions.ConnectionError("refused")):
            assert send_pagerduty_alert(**SAMPLE, routing_key="rkey") is False

    def test_uses_env_routing_key_when_no_override(self):
        mock_resp = MagicMock(status_code=202)
        mock_resp.json.return_value = {"dedup_key": "abc"}
        with patch("services.alerting.alerter.PAGERDUTY_ROUTING_KEY", "env_rkey"):
            with patch("services.alerting.alerter.requests.post",
                       return_value=mock_resp) as mock_post:
                send_pagerduty_alert(**SAMPLE)
        body = mock_post.call_args[1]["json"]
        assert body["routing_key"] == "env_rkey"


# ── Dispatcher: send_alerts ────────────────────────────────────────────────────

class TestSendAlerts:

    def test_returns_dict_with_all_four_channels(self):
        results = send_alerts(**SAMPLE)
        assert set(results.keys()) == {"slack", "teams", "email", "pagerduty"}

    def test_all_false_when_nothing_configured(self):
        """With no env vars set and no webhook URLs, every channel returns False."""
        with patch("services.alerting.alerter.SLACK_WEBHOOK_URL", ""):
            with patch("services.alerting.alerter.TEAMS_WEBHOOK_URL", ""):
                with patch("services.alerting.alerter.ALERT_EMAIL_FROM", ""):
                    with patch("services.alerting.alerter.PAGERDUTY_ROUTING_KEY", ""):
                        results = send_alerts(**SAMPLE)
        assert results == {"slack": False, "teams": False, "email": False, "pagerduty": False}

    def test_slack_true_when_slack_configured(self):
        mock_resp = MagicMock(status_code=200)
        with patch("services.alerting.alerter.SLACK_WEBHOOK_URL", "https://hooks.slack.com/x"):
            with patch("services.alerting.alerter.TEAMS_WEBHOOK_URL", ""):
                with patch("services.alerting.alerter.ALERT_EMAIL_FROM", ""):
                    with patch("services.alerting.alerter.PAGERDUTY_ROUTING_KEY", ""):
                        with patch("services.alerting.alerter.requests.post",
                                   return_value=mock_resp):
                            results = send_alerts(**SAMPLE)
        assert results["slack"] is True
        assert results["teams"] is False
        assert results["pagerduty"] is False

    def test_pagerduty_true_when_pagerduty_configured(self):
        mock_resp = MagicMock(status_code=202)
        mock_resp.json.return_value = {"dedup_key": "abc"}
        with patch("services.alerting.alerter.SLACK_WEBHOOK_URL", ""):
            with patch("services.alerting.alerter.TEAMS_WEBHOOK_URL", ""):
                with patch("services.alerting.alerter.ALERT_EMAIL_FROM", ""):
                    with patch("services.alerting.alerter.PAGERDUTY_ROUTING_KEY", "rkey"):
                        with patch("services.alerting.alerter.requests.post",
                                   return_value=mock_resp):
                            results = send_alerts(**SAMPLE)
        assert results["pagerduty"] is True
        assert results["slack"] is False

    def test_multiple_channels_fire_independently(self):
        """When both Slack and Teams are configured, both results are True."""
        slack_resp  = MagicMock(status_code=200)
        teams_resp  = MagicMock(status_code=200)

        def _post_side_effect(url, **kwargs):
            if "slack" in url:
                return slack_resp
            return teams_resp

        with patch("services.alerting.alerter.SLACK_WEBHOOK_URL", "https://hooks.slack.com/x"):
            with patch("services.alerting.alerter.TEAMS_WEBHOOK_URL", "https://outlook.office.com/x"):
                with patch("services.alerting.alerter.ALERT_EMAIL_FROM", ""):
                    with patch("services.alerting.alerter.PAGERDUTY_ROUTING_KEY", ""):
                        with patch("services.alerting.alerter.requests.post",
                                   side_effect=_post_side_effect):
                            results = send_alerts(**SAMPLE)
        assert results["slack"] is True
        assert results["teams"] is True

    def test_email_true_when_email_configured(self):
        mock_smtp = MagicMock()
        with patch("services.alerting.alerter.SLACK_WEBHOOK_URL", ""):
            with patch("services.alerting.alerter.TEAMS_WEBHOOK_URL", ""):
                with patch("services.alerting.alerter.ALERT_EMAIL_FROM", "alerts@example.com"):
                    with patch("services.alerting.alerter.ALERT_EMAIL_TO", "ops@example.com"):
                        with patch("services.alerting.alerter.SMTP_HOST", "smtp.example.com"):
                            with patch("services.alerting.alerter.PAGERDUTY_ROUTING_KEY", ""):
                                with patch("services.alerting.alerter.smtplib.SMTP",
                                           return_value=mock_smtp):
                                    results = send_alerts(**SAMPLE)
        assert results["email"] is True
