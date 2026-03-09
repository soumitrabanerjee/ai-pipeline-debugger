"""
Alerting Service — sends Slack notifications when a pipeline fails.

Configured via environment variable:
  SLACK_WEBHOOK_URL   — incoming webhook URL (disabled / no-op when not set)
  DASHBOARD_URL       — link embedded in the "View Dashboard" button
                        (default: http://localhost:5173)

Usage:
  from services.alerting.alerter import send_slack_alert

  sent = send_slack_alert(
      pipeline_name="customer_etl",
      run_id="run_20260308_001",
      error_type="ExecutorLostFailure",
      root_cause="Spark executor memory exceeded",
      fix="Increase spark.executor.memory to 8g",
  )

Alert layout (Sentry / Datadog style):
  ┌─────────────────────────────────────────┐
  │ ❌  Pipeline Failed · customer_etl      │  ← header
  ├─────────────────────────────────────────┤
  │ Pipeline  customer_etl  │ Error Type    │  ← two-column fields
  │ Run ID    run_001       │ ExecutorLost… │
  ├─────────────────────────────────────────┤
  │ 🔍 Root Cause                           │  ← AI analysis
  │   Spark executor memory exceeded        │
  ├─────────────────────────────────────────┤
  │ 💡 Suggested Fix                        │
  │   Increase spark.executor.memory to 8g  │
  ├─────────────────────────────────────────┤
  │ [ View Dashboard → ]                    │  ← action button
  ├─────────────────────────────────────────┤
  │ AI Pipeline Debugger · llama3.1:8b      │  ← footer context
  └─────────────────────────────────────────┘
"""

import os
import requests
from datetime import datetime, timezone

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
DASHBOARD_URL     = os.getenv("DASHBOARD_URL", "http://localhost:5173")

# Timeout for the outgoing Slack HTTP request
_REQUEST_TIMEOUT_S = 10

# Truncation limits so blocks don't exceed Slack's 3 000-char field limit
_MAX_CAUSE = 600
_MAX_FIX   = 400
_MAX_ERROR = 120


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def build_slack_payload(
    pipeline_name: str,
    run_id: str,
    error_type: str,
    root_cause: str,
    fix: str,
    severity: str = "ERROR",
    dashboard_url: str = "",
) -> dict:
    """
    Build a professional Slack Block Kit alert payload.

    Produces a multi-section message that matches the visual quality of
    enterprise observability tools (Sentry, Datadog, PagerDuty).

    Args:
        pipeline_name: Name of the failed pipeline.
        run_id:        Unique run identifier.
        error_type:    Short error signature / exception class.
        root_cause:    AI-generated root cause explanation.
        fix:           AI-generated suggested fix.
        severity:      Severity label (ERROR / WARN / CRITICAL). Default: ERROR.
        dashboard_url: Override for the dashboard button URL.
    """
    url        = dashboard_url or DASHBOARD_URL
    ts         = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sev        = severity.upper()
    sev_emoji  = {"CRITICAL": "🚨", "ERROR": "❌", "WARN": "⚠️"}.get(sev, "❌")
    run_short  = run_id[:40] + "…" if len(run_id) > 40 else run_id
    error_short = _truncate(error_type, _MAX_ERROR)

    blocks = [
        # ── Header ───────────────────────────────────────────────────────────
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{sev_emoji}  Pipeline Failed · {pipeline_name}",
                "emoji": True,
            },
        },

        # ── Two-column metadata ───────────────────────────────────────────────
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Pipeline*\n`{pipeline_name}`"},
                {"type": "mrkdwn", "text": f"*Severity*\n`{sev}`"},
                {"type": "mrkdwn", "text": f"*Run ID*\n`{run_short}`"},
                {"type": "mrkdwn", "text": f"*Detected*\n{ts}"},
            ],
        },

        # ── Error type ────────────────────────────────────────────────────────
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Error Type*\n```{error_short}```"},
            ],
        },

        {"type": "divider"},

        # ── AI root cause ─────────────────────────────────────────────────────
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🔍  Root Cause*\n{_truncate(root_cause, _MAX_CAUSE)}",
            },
        },

        # ── Suggested fix ─────────────────────────────────────────────────────
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*💡  Suggested Fix*\n{_truncate(fix, _MAX_FIX)}",
            },
        },

        {"type": "divider"},

        # ── Action button ─────────────────────────────────────────────────────
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Dashboard →", "emoji": True},
                    "style": "primary",
                    "url": url,
                },
            ],
        },

        # ── Footer context ────────────────────────────────────────────────────
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*AI Pipeline Debugger* · Powered by llama3.1:8b via Ollama · "
                        f"Run ID: `{run_short}`"
                    ),
                }
            ],
        },
    ]

    return {
        # Fallback text shown in notifications / unfurls
        "text": f"{sev_emoji} Pipeline *{pipeline_name}* failed — {error_short}",
        "blocks": blocks,
    }


def send_slack_alert(
    pipeline_name: str,
    run_id: str,
    error_type: str,
    root_cause: str,
    fix: str,
    webhook_url: str = "",
    severity: str = "ERROR",
    dashboard_url: str = "",
) -> bool:
    """
    Post a Block Kit failure alert to Slack.

    Returns True if the alert was sent successfully, False otherwise.
    When no webhook URL is configured the call is a silent no-op (returns False).

    Args:
        pipeline_name: Name of the failed pipeline.
        run_id:        Unique identifier for this run.
        error_type:    Short error signature (e.g. "ExecutorLostFailure").
        root_cause:    AI-generated root cause explanation.
        fix:           AI-generated suggested fix.
        webhook_url:   Override URL (for testing). Falls back to SLACK_WEBHOOK_URL env var.
        severity:      Severity label forwarded to the Block Kit header (ERROR / WARN / CRITICAL).
        dashboard_url: Override for the "View Dashboard" button URL.
    """
    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        return False  # Alerting disabled — no webhook configured

    payload = build_slack_payload(
        pipeline_name=pipeline_name,
        run_id=run_id,
        error_type=error_type,
        root_cause=root_cause,
        fix=fix,
        severity=severity,
        dashboard_url=dashboard_url,
    )

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
