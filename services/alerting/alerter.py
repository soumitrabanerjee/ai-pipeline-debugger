"""
Alerting Service — sends Slack notifications when a pipeline fails.

Configured via environment variable:
  SLACK_WEBHOOK_URL — incoming webhook URL (disabled / no-op when not set)

Usage:
  from services.alerting.alerter import send_slack_alert

  sent = send_slack_alert(
      pipeline_name="customer_etl",
      run_id="run_20260308_001",
      error_type="ExecutorLostFailure",
      root_cause="Spark executor memory exceeded",
      fix="Increase spark.executor.memory to 8g",
  )
"""

import os
import requests

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# Timeout for the outgoing Slack HTTP request
_REQUEST_TIMEOUT_S = 10


def build_slack_payload(
    pipeline_name: str,
    run_id: str,
    error_type: str,
    root_cause: str,
    fix: str,
) -> dict:
    """Build the Slack Block Kit message payload."""
    return {
        "text": f":red_circle: Pipeline *{pipeline_name}* failed",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Pipeline Failed: {pipeline_name}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Run ID:*\n{run_id}"},
                    {"type": "mrkdwn", "text": f"*Error:*\n{error_type}"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Root Cause:*\n{root_cause}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Suggested Fix:*\n{fix}",
                },
            },
        ],
    }


def send_slack_alert(
    pipeline_name: str,
    run_id: str,
    error_type: str,
    root_cause: str,
    fix: str,
    webhook_url: str = "",
) -> bool:
    """
    Post a failure alert to Slack.

    Returns True if the alert was sent successfully, False otherwise.
    When no webhook URL is configured the call is a silent no-op (returns False).

    Args:
        pipeline_name: Name of the failed pipeline.
        run_id:        Unique identifier for this run.
        error_type:    Short error signature (e.g. "ExecutorLostFailure").
        root_cause:    AI-generated root cause explanation.
        fix:           AI-generated suggested fix.
        webhook_url:   Override URL (for testing). Falls back to SLACK_WEBHOOK_URL env var.
    """
    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        return False  # Alerting disabled — no webhook configured

    payload = build_slack_payload(pipeline_name, run_id, error_type, root_cause, fix)

    try:
        response = requests.post(url, json=payload, timeout=_REQUEST_TIMEOUT_S)
        if response.status_code == 200:
            print(f"[alerter] Slack alert sent for pipeline '{pipeline_name}' run '{run_id}'")
            return True
        print(f"[alerter] Slack returned HTTP {response.status_code}: {response.text}")
        return False
    except requests.exceptions.Timeout:
        print(f"[alerter] Slack request timed out for pipeline '{pipeline_name}'")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"[alerter] Slack connection error for pipeline '{pipeline_name}': {e}")
        return False
