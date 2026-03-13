"""
parser.py — Public interface for the log processing layer.

This module is the single import point used by queue-worker/worker.py.
It delegates to advanced_parser.py for production-grade exception extraction
and exposes a backwards-compatible ParsedError dataclass.

Upgrade path from the old naive implementation:
  OLD: signature = message.split(":")[0]   # breaks on multi-line traces
  NEW: full exception chain, causal root, user frames, severity classification

Usage (worker.py):
    from parser import extract_error
    parsed = extract_error(message)
    # parsed.signature  — deduplication key  e.g. "EXECUTOR_FAILURE:PythonException"
    # parsed.severity   — "critical"|"high"|"medium"|"low"
    # parsed.summary    — compact debug context for LLM prompt (~1000 chars)
"""

from dataclasses import dataclass
from advanced_parser import parse_single_message, ExceptionBlock


@dataclass
class ParsedError:
    """
    Backwards-compatible result type consumed by queue-worker/worker.py.

    Fields
    ------
    signature : str
        Deduplication key in the form "CATEGORY:ExceptionClass".
        Used as error_type in the errors table unique constraint
        (workspace_id, pipeline_name, error_type).

    severity : str
        "critical" | "high" | "medium" | "low"
        Drives Slack alert urgency and dashboard badge colour.

    summary : str
        Compact, signal-dense context string (≤1000 chars) sent to Claude
        as pipeline_context.  Contains task context, exception chain,
        causal root, and user-code stack frames — no JVM internals.
    """
    signature: str
    severity:  str
    summary:   str


def extract_error(message: str) -> ParsedError:
    """
    Parse a raw error message/log chunk into a structured ParsedError.

    Delegates to advanced_parser.parse_single_message() which handles:
      • Spark Java stack traces + Caused by: chains
      • PythonException wrappers (PySpark UDF failures)
      • Airflow Python tracebacks
      • OOM / OutOfMemoryError patterns
      • Generic single-line error messages (fallback)

    Parameters
    ----------
    message : str
        Raw log message from the Redis stream (may be single-line or
        multi-line depending on how the webhook / agent sent it).

    Returns
    -------
    ParsedError
        Structured result with signature, severity, and compact summary.
    """
    block: ExceptionBlock = parse_single_message(message)

    return ParsedError(
        signature = block.signature(),
        severity  = block.severity,
        summary   = block.to_debug_context(max_chars=1000),
    )
