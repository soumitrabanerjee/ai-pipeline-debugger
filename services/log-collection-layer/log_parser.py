"""
Log line parser — converts raw log lines from Spark/Airflow/dbt
into the normalized LogEvent dict the ingestion API expects.

Handles three formats:

  Airflow-style:
    [2026-03-08T10:23:45.123+0530] {taskinstance.py:1234} ERROR - ExecutorLostFailure: ...

  PySpark native (Log4j default):
    26/03/09 22:02:23 ERROR TaskSetManager: Task 0 in stage 0.0 failed 4 times

  Spark/generic (ISO-8601):
    2026-03-08T10:23:45.123Z ERROR ExecutorLostFailure: ...

Recognized log levels: ERROR, WARN/WARNING, INFO, DEBUG.
Only ERROR lines are forwarded to the ingestion API by the agent.
"""

import re
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

# ── patterns ──────────────────────────────────────────────────────────────────

# Airflow: [2026-03-08T10:23:45.123+0530] {module.py:42} LEVEL - message
_AIRFLOW_RE = re.compile(
    r"\[(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[,.]?\d*(?:[+-]\d{2}:?\d{2}|Z)?)\]"
    r"\s+\{[^}]*\}"
    r"\s+(?P<level>ERROR|WARN(?:ING)?|INFO|DEBUG)"
    r"\s+-\s+(?P<message>.+)"
)

# PySpark native Log4j: 26/03/09 22:02:23 ERROR TaskSetManager: Task 0 failed...
_PYSPARK_RE = re.compile(
    r"(?P<ts>\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})"
    r"\s+(?P<level>ERROR|WARN(?:ING)?|INFO|DEBUG)"
    r"\s+\S+:\s+(?P<message>.+)"
)

# Spark / generic: 2026-03-08T10:23:45.123Z LEVEL message
_SPARK_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?)"
    r"\s+(?P<level>ERROR|WARN(?:ING)?|INFO|DEBUG)"
    r"\s+(?P<message>.+)"
)

# Timestamp normalisation helpers
_TS_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S,%f",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%y/%m/%d %H:%M:%S",   # PySpark Log4j: 26/03/09 22:02:23
]


def _normalise_ts(raw: str) -> str:
    """Return ISO-8601 UTC timestamp string, or 'now' fallback."""
    raw = raw.strip()
    # Strip timezone offsets like +0530 or +05:30 so strptime can parse cleanly
    raw = re.sub(r'[+-]\d{2}:?\d{2}$', '', raw).rstrip()
    for fmt in _TS_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── public API ─────────────────────────────────────────────────────────────────

@dataclass
class ParsedLine:
    level: str               # "ERROR" | "WARN" | "INFO" | "DEBUG"
    message: str
    timestamp: str           # ISO-8601 UTC
    source_format: str       # "airflow" | "spark" | "unknown"
    raw: str = field(repr=False)


def parse_log_line(line: str) -> Optional[ParsedLine]:
    """
    Parse a single log line.

    Returns a ParsedLine if the line matches a known format, None otherwise.
    Normalises WARN / WARNING → WARN.
    """
    line = line.rstrip()
    if not line:
        return None

    for pattern, fmt in ((_AIRFLOW_RE, "airflow"), (_PYSPARK_RE, "spark"), (_SPARK_RE, "spark")):
        m = pattern.match(line)
        if m:
            level = m.group("level").upper()
            if level == "WARNING":
                level = "WARN"
            return ParsedLine(
                level=level,
                message=m.group("message").strip(),
                timestamp=_normalise_ts(m.group("ts")),
                source_format=fmt,
                raw=line,
            )

    return None


def build_ingest_payload(
    parsed: ParsedLine,
    job_id: str,
    source: str = "agent",
    workspace_id: str = "default",
    task_id: Optional[str] = None,
) -> dict:
    """
    Turn a ParsedLine into the dict the ingestion API's POST /ingest expects.
    A fresh run_id UUID is generated for each error line.
    """
    return {
        "source": source,
        "workspace_id": workspace_id,
        "job_id": job_id,
        "run_id": str(uuid.uuid4()),
        "task_id": task_id,
        "level": parsed.level,
        "timestamp": parsed.timestamp,
        "message": parsed.message,
    }
