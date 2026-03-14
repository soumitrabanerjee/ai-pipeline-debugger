"""
Alerting Service — sends failure notifications across multiple channels.

Channels
--------
  Slack      — Incoming Webhook (Block Kit)
  Teams      — Incoming Webhook (MessageCard)
  Email      — SMTP (HTML email via smtplib)
  PagerDuty  — Events API v2 (trigger incident)

All channels are opt-in via environment variables. Missing config = silent no-op.

Environment variables
---------------------
  Slack:
    SLACK_WEBHOOK_URL   — incoming webhook URL
    DASHBOARD_URL       — link for the "View Dashboard" button (default: http://localhost:5173)

  Teams:
    TEAMS_WEBHOOK_URL   — incoming webhook URL

  Email:
    ALERT_EMAIL_FROM    — sender address  (e.g. alerts@company.com)
    ALERT_EMAIL_TO      — recipient(s), comma-separated
    SMTP_HOST           — SMTP server hostname  (default: localhost)
    SMTP_PORT           — SMTP port (default: 587)
    SMTP_USER           — SMTP auth username (optional)
    SMTP_PASSWORD       — SMTP auth password (optional)
    SMTP_USE_SSL        — set to "1" or "true" for SMTP_SSL (implicit TLS)

  PagerDuty:
    PAGERDUTY_ROUTING_KEY — Integration key from Events API v2 integration

Usage
-----
  from services.alerting.alerter import send_alerts

  results = send_alerts(
      pipeline_name="customer_etl",
      run_id="run_001",
      error_type="OOM:OutOfMemoryError",
      root_cause="Spark executor ran out of heap",
      fix="Increase spark.executor.memory to 8g",
      severity="CRITICAL",
  )
  # returns {"slack": True, "teams": False, "email": False, "pagerduty": True}
"""

import os
import smtplib
import requests
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Shared config ──────────────────────────────────────────────────────────────

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:5173")

_REQUEST_TIMEOUT_S = 10

# Truncation limits
_MAX_CAUSE = 600
_MAX_FIX   = 400
_MAX_ERROR = 120


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _severity_color(severity: str) -> str:
    """Return a hex color for the severity level (no leading #)."""
    return {"CRITICAL": "8B0000", "ERROR": "CC0000", "WARN": "FFA500"}.get(
        severity.upper(), "CC0000"
    )


def _severity_emoji(severity: str) -> str:
    return {"CRITICAL": "🚨", "ERROR": "❌", "WARN": "⚠️"}.get(severity.upper(), "❌")


# ── Slack ──────────────────────────────────────────────────────────────────────

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


def build_slack_payload(
    pipeline_name: str,
    run_id: str,
    error_type: str,
    root_cause: str,
    fix: str,
    severity: str = "ERROR",
    dashboard_url: str = "",
) -> dict:
    """Build a Slack Block Kit alert payload."""
    url        = dashboard_url or DASHBOARD_URL
    ts         = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sev        = severity.upper()
    sev_emoji  = _severity_emoji(sev)
    run_short  = run_id[:40] + "…" if len(run_id) > 40 else run_id
    error_short = _truncate(error_type, _MAX_ERROR)

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{sev_emoji}  Pipeline Failed · {pipeline_name}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Pipeline*\n`{pipeline_name}`"},
                {"type": "mrkdwn", "text": f"*Severity*\n`{sev}`"},
                {"type": "mrkdwn", "text": f"*Run ID*\n`{run_short}`"},
                {"type": "mrkdwn", "text": f"*Detected*\n{ts}"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Error Type*\n```{error_short}```"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🔍  Root Cause*\n{_truncate(root_cause, _MAX_CAUSE)}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*💡  Suggested Fix*\n{_truncate(fix, _MAX_FIX)}",
            },
        },
        {"type": "divider"},
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
    """Post a Block Kit failure alert to Slack. Returns True on success."""
    url = webhook_url or SLACK_WEBHOOK_URL
    if not url:
        return False

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
            print(f"[alerter] Slack alert sent for pipeline '{pipeline_name}'")
            return True
        print(f"[alerter] Slack returned HTTP {response.status_code}: {response.text}")
        return False
    except requests.exceptions.Timeout:
        print(f"[alerter] Slack request timed out for pipeline '{pipeline_name}'")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"[alerter] Slack connection error for pipeline '{pipeline_name}': {e}")
        return False


# ── Microsoft Teams ────────────────────────────────────────────────────────────

TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")


def build_teams_payload(
    pipeline_name: str,
    run_id: str,
    error_type: str,
    root_cause: str,
    fix: str,
    severity: str = "ERROR",
    dashboard_url: str = "",
) -> dict:
    """
    Build a Microsoft Teams MessageCard payload.

    Uses the legacy MessageCard format which works for all Teams incoming
    webhooks without requiring app registration.
    """
    url         = dashboard_url or DASHBOARD_URL
    sev         = severity.upper()
    color       = _severity_color(sev)
    sev_emoji   = _severity_emoji(sev)
    run_short   = run_id[:40] + "…" if len(run_id) > 40 else run_id
    error_short = _truncate(error_type, _MAX_ERROR)
    ts          = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": color,
        "summary": f"Pipeline {pipeline_name} failed",
        "sections": [
            {
                "activityTitle": f"{sev_emoji} **Pipeline Failed** · `{pipeline_name}`",
                "activitySubtitle": f"Severity: **{sev}** · Detected: {ts}",
                "facts": [
                    {"name": "Pipeline", "value": pipeline_name},
                    {"name": "Run ID",   "value": run_short},
                    {"name": "Error",    "value": error_short},
                ],
                "markdown": True,
            },
            {
                "title": "🔍 Root Cause",
                "text": _truncate(root_cause, _MAX_CAUSE),
            },
            {
                "title": "💡 Suggested Fix",
                "text": _truncate(fix, _MAX_FIX),
            },
        ],
        "potentialAction": [
            {
                "@type": "OpenUri",
                "name": "View Dashboard →",
                "targets": [{"os": "default", "uri": url}],
            }
        ],
    }


def send_teams_alert(
    pipeline_name: str,
    run_id: str,
    error_type: str,
    root_cause: str,
    fix: str,
    webhook_url: str = "",
    severity: str = "ERROR",
    dashboard_url: str = "",
) -> bool:
    """Post a MessageCard alert to Microsoft Teams. Returns True on success."""
    url = webhook_url or TEAMS_WEBHOOK_URL
    if not url:
        return False

    payload = build_teams_payload(
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
        # Teams webhooks return HTTP 200 with body "1" on success
        if response.status_code == 200:
            print(f"[alerter] Teams alert sent for pipeline '{pipeline_name}'")
            return True
        print(f"[alerter] Teams returned HTTP {response.status_code}: {response.text}")
        return False
    except requests.exceptions.Timeout:
        print(f"[alerter] Teams request timed out for pipeline '{pipeline_name}'")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"[alerter] Teams connection error for pipeline '{pipeline_name}': {e}")
        return False


# ── Email (SMTP) ───────────────────────────────────────────────────────────────

ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
ALERT_EMAIL_TO   = os.getenv("ALERT_EMAIL_TO",   "")
SMTP_HOST        = os.getenv("SMTP_HOST",        "localhost")
SMTP_PORT        = int(os.getenv("SMTP_PORT",    "587"))
SMTP_USER        = os.getenv("SMTP_USER",        "")
SMTP_PASSWORD    = os.getenv("SMTP_PASSWORD",    "")
SMTP_USE_SSL     = os.getenv("SMTP_USE_SSL",     "").lower() in ("1", "true", "yes")


def build_email_message(
    pipeline_name: str,
    run_id: str,
    error_type: str,
    root_cause: str,
    fix: str,
    severity: str = "ERROR",
    dashboard_url: str = "",
    from_addr: str = "",
    to_addrs: list[str] | None = None,
) -> MIMEMultipart:
    """
    Build an HTML email alert as a MIMEMultipart object.

    Returns a MIMEMultipart ready to be passed to smtplib.sendmail().
    """
    url         = dashboard_url or DASHBOARD_URL
    sev         = severity.upper()
    color       = "#" + _severity_color(sev)
    sev_emoji   = _severity_emoji(sev)
    run_short   = run_id[:40] + "…" if len(run_id) > 40 else run_id
    error_short = _truncate(error_type, _MAX_ERROR)
    ts          = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    recipients  = to_addrs or []

    subject = f"{sev_emoji} Pipeline Failed: {pipeline_name} [{sev}]"

    html = f"""
<html><body style="font-family:sans-serif;color:#333;max-width:640px;margin:auto;">
  <div style="background:{color};padding:16px 24px;border-radius:6px 6px 0 0;">
    <h2 style="color:#fff;margin:0;">{sev_emoji} Pipeline Failed &middot; {pipeline_name}</h2>
  </div>
  <div style="border:1px solid #ddd;border-top:none;padding:20px;border-radius:0 0 6px 6px;">
    <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
      <tr>
        <td style="padding:6px;"><strong>Pipeline</strong></td>
        <td style="padding:6px;font-family:monospace;">{pipeline_name}</td>
        <td style="padding:6px;"><strong>Severity</strong></td>
        <td style="padding:6px;font-family:monospace;">{sev}</td>
      </tr>
      <tr style="background:#f9f9f9;">
        <td style="padding:6px;"><strong>Run ID</strong></td>
        <td style="padding:6px;font-family:monospace;">{run_short}</td>
        <td style="padding:6px;"><strong>Detected</strong></td>
        <td style="padding:6px;">{ts}</td>
      </tr>
      <tr>
        <td style="padding:6px;"><strong>Error Type</strong></td>
        <td style="padding:6px;font-family:monospace;" colspan="3">{error_short}</td>
      </tr>
    </table>
    <hr style="border:none;border-top:1px solid #eee;margin:16px 0;">
    <h3 style="margin:0 0 8px;">🔍 Root Cause</h3>
    <p style="margin:0 0 16px;line-height:1.6;">{_truncate(root_cause, _MAX_CAUSE)}</p>
    <h3 style="margin:0 0 8px;">💡 Suggested Fix</h3>
    <p style="margin:0 0 24px;line-height:1.6;">{_truncate(fix, _MAX_FIX)}</p>
    <a href="{url}" style="background:#0066cc;color:#fff;padding:10px 20px;
       border-radius:4px;text-decoration:none;font-weight:bold;">View Dashboard →</a>
    <p style="margin-top:24px;font-size:12px;color:#999;">
      AI Pipeline Debugger &middot; Run ID: {run_short}
    </p>
  </div>
</body></html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))
    return msg


def send_email_alert(
    pipeline_name: str,
    run_id: str,
    error_type: str,
    root_cause: str,
    fix: str,
    severity: str = "ERROR",
    dashboard_url: str = "",
    from_addr: str = "",
    to_addrs: list[str] | None = None,
    smtp_host: str = "",
    smtp_port: int = 0,
    smtp_user: str = "",
    smtp_password: str = "",
    smtp_use_ssl: bool | None = None,
) -> bool:
    """
    Send an HTML email alert via SMTP. Returns True on success.

    All SMTP parameters fall back to the module-level env-var constants when
    not provided, so callers in production only need to set env vars.
    """
    sender     = from_addr  or ALERT_EMAIL_FROM
    recipients_list = to_addrs or (
        [a.strip() for a in ALERT_EMAIL_TO.split(",") if a.strip()]
        if ALERT_EMAIL_TO else []
    )

    if not sender or not recipients_list:
        return False  # Email disabled — not configured

    host     = smtp_host     or SMTP_HOST
    port     = smtp_port     or SMTP_PORT
    user     = smtp_user     or SMTP_USER
    password = smtp_password or SMTP_PASSWORD
    use_ssl  = smtp_use_ssl if smtp_use_ssl is not None else SMTP_USE_SSL

    msg = build_email_message(
        pipeline_name=pipeline_name,
        run_id=run_id,
        error_type=error_type,
        root_cause=root_cause,
        fix=fix,
        severity=severity,
        dashboard_url=dashboard_url,
        from_addr=sender,
        to_addrs=recipients_list,
    )

    try:
        if use_ssl:
            smtp = smtplib.SMTP_SSL(host, port, timeout=_REQUEST_TIMEOUT_S)
        else:
            smtp = smtplib.SMTP(host, port, timeout=_REQUEST_TIMEOUT_S)
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()

        if user and password:
            smtp.login(user, password)

        smtp.sendmail(sender, recipients_list, msg.as_string())
        smtp.quit()
        print(f"[alerter] Email alert sent for pipeline '{pipeline_name}' → {recipients_list}")
        return True

    except smtplib.SMTPException as e:
        print(f"[alerter] SMTP error for pipeline '{pipeline_name}': {e}")
        return False
    except OSError as e:
        print(f"[alerter] Email connection error for pipeline '{pipeline_name}': {e}")
        return False


# ── PagerDuty ──────────────────────────────────────────────────────────────────

PAGERDUTY_ROUTING_KEY = os.getenv("PAGERDUTY_ROUTING_KEY", "")
_PAGERDUTY_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"

_PD_SEVERITY_MAP = {
    "CRITICAL": "critical",
    "ERROR":    "error",
    "WARN":     "warning",
}


def build_pagerduty_payload(
    pipeline_name: str,
    run_id: str,
    error_type: str,
    root_cause: str,
    fix: str,
    severity: str = "ERROR",
    routing_key: str = "",
) -> dict:
    """
    Build a PagerDuty Events API v2 trigger payload.

    https://developer.pagerduty.com/docs/ZG9jOjExMDI5NTgw-send-an-alert-event
    """
    sev        = severity.upper()
    pd_sev     = _PD_SEVERITY_MAP.get(sev, "error")
    error_short = _truncate(error_type, _MAX_ERROR)

    return {
        "routing_key":  routing_key or PAGERDUTY_ROUTING_KEY,
        "event_action": "trigger",
        "dedup_key":    f"{pipeline_name}:{error_short}",
        "payload": {
            "summary":  f"Pipeline {pipeline_name} failed — {error_short}",
            "severity": pd_sev,
            "source":   "ai-pipeline-debugger",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "custom_details": {
                "pipeline_name": pipeline_name,
                "run_id":        run_id,
                "error_type":    error_short,
                "root_cause":    _truncate(root_cause, _MAX_CAUSE),
                "suggested_fix": _truncate(fix, _MAX_FIX),
            },
        },
    }


def send_pagerduty_alert(
    pipeline_name: str,
    run_id: str,
    error_type: str,
    root_cause: str,
    fix: str,
    severity: str = "ERROR",
    routing_key: str = "",
) -> bool:
    """
    Trigger a PagerDuty incident via Events API v2. Returns True on success.
    PagerDuty returns HTTP 202 (Accepted) on success.
    """
    key = routing_key or PAGERDUTY_ROUTING_KEY
    if not key:
        return False

    payload = build_pagerduty_payload(
        pipeline_name=pipeline_name,
        run_id=run_id,
        error_type=error_type,
        root_cause=root_cause,
        fix=fix,
        severity=severity,
        routing_key=key,
    )

    try:
        response = requests.post(
            _PAGERDUTY_EVENTS_URL,
            json=payload,
            timeout=_REQUEST_TIMEOUT_S,
            headers={"Content-Type": "application/json"},
        )
        # PagerDuty returns 202 Accepted on success
        if response.status_code == 202:
            dedup = response.json().get("dedup_key", "")
            print(
                f"[alerter] PagerDuty alert triggered for pipeline '{pipeline_name}' "
                f"(dedup_key={dedup})"
            )
            return True
        print(f"[alerter] PagerDuty returned HTTP {response.status_code}: {response.text}")
        return False
    except requests.exceptions.Timeout:
        print(f"[alerter] PagerDuty request timed out for pipeline '{pipeline_name}'")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"[alerter] PagerDuty connection error for pipeline '{pipeline_name}': {e}")
        return False


# ── Unified dispatcher ─────────────────────────────────────────────────────────

def send_alerts(
    pipeline_name: str,
    run_id: str,
    error_type: str,
    root_cause: str,
    fix: str,
    severity: str = "ERROR",
    dashboard_url: str = "",
) -> dict[str, bool]:
    """
    Fire all configured alert channels and return a per-channel result map.

    A channel is considered "configured" when its required env var is set.
    Unconfigured channels are silently skipped and reported as False.

    Returns:
        {
            "slack":      True | False,
            "teams":      True | False,
            "email":      True | False,
            "pagerduty":  True | False,
        }
    """
    kwargs = dict(
        pipeline_name=pipeline_name,
        run_id=run_id,
        error_type=error_type,
        root_cause=root_cause,
        fix=fix,
        severity=severity,
    )

    results = {
        "slack":     send_slack_alert(**kwargs, dashboard_url=dashboard_url),
        "teams":     send_teams_alert(**kwargs, dashboard_url=dashboard_url),
        "email":     send_email_alert(**kwargs, dashboard_url=dashboard_url),
        "pagerduty": send_pagerduty_alert(**kwargs),
    }

    sent = [ch for ch, ok in results.items() if ok]
    if sent:
        print(f"[alerter] Alerts dispatched via: {', '.join(sent)}")
    else:
        print("[alerter] No alert channels configured — skipping")

    return results
