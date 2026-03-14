"""
Root Cause Engine — scores and ranks hypotheses about the root cause of a pipeline error.

Two hypothesis sources:
  1. AI hypothesis — extracted from Claude's /analyze response (confidence_score field)
  2. Rule hypothesis — derived from the deterministic exception catalogue

The engine ranks all candidates by score (descending) and returns the top hypothesis
for storage and alerting.  Rules win only when the AI service fails or returns low
confidence; a high-confidence AI result (≥0.90) always beats a rule hypothesis.
"""

from __future__ import annotations
from typing import Optional


# ── Rule catalogue ─────────────────────────────────────────────────────────────

# Maps exception category (as produced by advanced_parser's _EXCEPTION_CATALOGUE)
# to a rule-based hypothesis + fix suggestion.
# Scores are kept ≤ 0.88 so a high-confidence Claude result (≥ 0.90) always wins;
# rules surface only when AI analysis fails or returns low confidence.

_RULE_CATALOGUE: dict[str, dict] = {
    "OOM": {
        "hypothesis": (
            "Spark executor or driver ran out of heap memory. "
            "GC overhead may have triggered the failure."
        ),
        "fix": (
            "Increase spark.executor.memory and spark.driver.memory. "
            "Enable off-heap memory if the dataset is large. "
            "Consider repartitioning to reduce per-task data volume."
        ),
        "score": 0.82,
    },
    "BROADCAST_OOM": {
        "hypothesis": (
            "Broadcast join exceeded available memory on the executor. "
            "The table being broadcast is too large."
        ),
        "fix": (
            "Raise spark.sql.autoBroadcastJoinThreshold or disable broadcasting with "
            "spark.sql.autoBroadcastJoinThreshold=-1. Switch to a sort-merge join."
        ),
        "score": 0.80,
    },
    "EXECUTOR_FAILURE": {
        "hypothesis": (
            "A Spark executor was lost due to OOM, task timeout, or host failure. "
            "The stage failed after exhausting retries."
        ),
        "fix": (
            "Check executor logs for the root cause. Increase spark.task.maxFailures, "
            "add executor memory, or reduce partition size with spark.sql.shuffle.partitions."
        ),
        "score": 0.78,
    },
    "DATA_TYPE": {
        "hypothesis": (
            "A data type mismatch or unexpected value caused a Python or Spark type error "
            "during transformation."
        ),
        "fix": (
            "Add schema validation before the transform step. Cast columns explicitly and "
            "handle nulls. Check source data for schema drift."
        ),
        "score": 0.78,
    },
    "MISSING_KEY": {
        "hypothesis": (
            "A required dictionary key was missing in the input data, indicating schema drift "
            "or incomplete upstream data."
        ),
        "fix": (
            "Use dict.get() with a default value or add an explicit key-presence check. "
            "Validate the upstream schema before processing."
        ),
        "score": 0.77,
    },
    "MISSING_FILE": {
        "hypothesis": (
            "A required input file or resource was not found. "
            "The upstream write may have failed or the path is misconfigured."
        ),
        "fix": (
            "Verify the source path exists before reading. "
            "Add a file-existence check in the DAG. Check upstream pipeline status."
        ),
        "score": 0.77,
    },
    "SCHEMA_MISMATCH": {
        "hypothesis": (
            "Column resolution failed at query planning time. "
            "A column name or type is inconsistent with the registered schema."
        ),
        "fix": (
            "Run DESCRIBE on the affected table. Ensure the DataFrame schema matches the "
            "expected schema. Re-run any pending schema migrations."
        ),
        "score": 0.80,
    },
    "NETWORK": {
        "hypothesis": (
            "A downstream service or data source was unreachable. "
            "The connection was refused or timed out."
        ),
        "fix": (
            "Check network connectivity and firewall rules. "
            "Verify the target host and port. Add retry logic with exponential backoff."
        ),
        "score": 0.75,
    },
    "IO_ERROR": {
        "hypothesis": (
            "An I/O error occurred reading from or writing to a storage backend "
            "(S3, GCS, HDFS, or local disk)."
        ),
        "fix": (
            "Check storage credentials, bucket/path permissions, and available disk space. "
            "Retry with smaller batch sizes."
        ),
        "score": 0.74,
    },
    "TIMEOUT": {
        "hypothesis": (
            "A task exceeded its configured time limit. "
            "Resource contention or slow I/O may be the cause."
        ),
        "fix": (
            "Increase the task timeout. Profile the slow task with Spark UI. "
            "Check for data skew causing one partition to dominate."
        ),
        "score": 0.74,
    },
    "NULL_REF": {
        "hypothesis": (
            "A null pointer was dereferenced. "
            "Nullable data entered a code path that assumed non-null values."
        ),
        "fix": (
            "Add null checks or use Option/getOrElse patterns. "
            "Filter null rows before the transform. Add DataFrame.na.drop() where appropriate."
        ),
        "score": 0.72,
    },
    "PERMISSIONS": {
        "hypothesis": (
            "The service account or IAM role lacks required permissions on the target resource."
        ),
        "fix": (
            "Review IAM policies for the pipeline service account. "
            "Grant the minimum required permissions on the storage bucket or API endpoint."
        ),
        "score": 0.78,
    },
    "CLASSPATH": {
        "hypothesis": (
            "A required Java class or method was not found at runtime. "
            "The JAR or dependency may be missing from the cluster classpath."
        ),
        "fix": (
            "Verify spark.jars and spark.executor.extraClassPath configuration. "
            "Ensure the dependency version matches what was compiled against."
        ),
        "score": 0.73,
    },
    "DIVIDE_BY_ZERO": {
        "hypothesis": (
            "A division by zero occurred in user code, likely due to an empty partition "
            "or a zero-valued denominator in the data."
        ),
        "fix": (
            "Guard division operations with a denominator check "
            "(e.g. x / y if y != 0 else default). "
            "Add data validation before the compute step."
        ),
        "score": 0.76,
    },
    "AIRFLOW_INTERNAL": {
        "hypothesis": (
            "An Airflow-internal error occurred, such as a DAG run conflict "
            "or deferred task state issue."
        ),
        "fix": (
            "Check the Airflow webserver logs. Clear the failed task instance and retry. "
            "If DagRunAlreadyExists, delete the stale run first."
        ),
        "score": 0.70,
    },
    "ENCODING": {
        "hypothesis": (
            "A Unicode encode/decode error occurred. "
            "The data contains characters outside the expected character set."
        ),
        "fix": (
            "Specify encoding explicitly (e.g. open(..., encoding='utf-8', errors='replace')). "
            "Validate source file encoding before ingestion."
        ),
        "score": 0.71,
    },
    "ASSERTION": {
        "hypothesis": (
            "An assertion failed in user code or a data quality check, "
            "indicating unexpected data values or pipeline state."
        ),
        "fix": (
            "Review the assertion condition and the data that triggered it. "
            "Add logging before the assertion to capture the offending values."
        ),
        "score": 0.72,
    },
}


# ── Core functions ─────────────────────────────────────────────────────────────

def rank_hypotheses(candidates: list[dict]) -> list[dict]:
    """Sort hypothesis candidates by score descending. Original list is not mutated."""
    return sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)


def _rule_hypothesis(parsed_error) -> Optional[dict]:
    """
    Look up the parsed error category in the rule catalogue.

    Parameters
    ----------
    parsed_error
        Object with a .signature attribute in "CATEGORY:ClassName" format
        (as returned by parser.extract_error()).

    Returns
    -------
    dict | None
        Rule hypothesis dict or None if the category has no catalogue entry.
    """
    if parsed_error is None:
        return None
    sig = getattr(parsed_error, "signature", "") or ""
    category = sig.split(":")[0]
    entry = _RULE_CATALOGUE.get(category)
    if not entry:
        return None
    return {
        "source":     "rule",
        "hypothesis": entry["hypothesis"],
        "fix":        entry["fix"],
        "score":      entry["score"],
    }


def build_hypotheses(ai_result: dict, parsed_error=None) -> list[dict]:
    """
    Assemble the full hypothesis pool from all available sources.

    Sources
    -------
    1. AI hypothesis  — from Claude's /analyze response.  Uses confidence_score
       directly as the ranking score.  Excluded when the AI service was
       unavailable (root_cause contains sentinel phrases).
    2. Rule hypothesis — deterministic lookup from _RULE_CATALOGUE keyed on
       the parsed exception category.

    Parameters
    ----------
    ai_result : dict
        Response from analyze_with_ai() — keys: root_cause, suggested_fix,
        confidence_score (optional, defaults to 0.5).
    parsed_error : ParsedError | None
        Result of extract_error() — needs .signature attribute.

    Returns
    -------
    list[dict]
        Each element: {source, hypothesis, fix, score}
    """
    candidates: list[dict] = []

    # ── 1. AI hypothesis ──────────────────────────────────────────────────────
    root_cause = (ai_result or {}).get("root_cause", "")
    root_lower = root_cause.lower()
    ai_is_fallback = (
        "unavailable" in root_lower
        or "analysis failed" in root_lower
        or not root_cause.strip()
    )
    if not ai_is_fallback:
        candidates.append({
            "source":     "ai",
            "hypothesis": root_cause,
            "fix":        (ai_result or {}).get("suggested_fix", ""),
            "score":      float((ai_result or {}).get("confidence_score", 0.5)),
        })

    # ── 2. Rule hypothesis ────────────────────────────────────────────────────
    rule = _rule_hypothesis(parsed_error)
    if rule:
        candidates.append(rule)

    return candidates


def select_top(candidates: list[dict]) -> Optional[dict]:
    """
    Return the highest-scoring hypothesis, or None if candidates is empty.

    Parameters
    ----------
    candidates : list[dict]
        Output of build_hypotheses().

    Returns
    -------
    dict | None
    """
    ranked = rank_hypotheses(candidates)
    return ranked[0] if ranked else None
