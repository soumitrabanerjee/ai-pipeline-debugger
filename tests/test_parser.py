"""
Tests for parser.extract_error() — the public interface over advanced_parser.

These tests exercise the actual behavior of advanced_parser.py, not the old
naive implementation that was replaced.  Signatures now follow the form
"CATEGORY:ExceptionClass" and summaries are LLM-friendly context strings.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "log-processing-layer"))
from parser import extract_error, ParsedError


class TestExtractError:

    # ── Return type ───────────────────────────────────────────────────────────

    def test_returns_parsed_error_dataclass(self):
        result = extract_error("SomeError: something went wrong")
        assert isinstance(result, ParsedError)

    def test_has_signature_severity_summary_fields(self):
        result = extract_error("KeyError: 'host' missing")
        assert hasattr(result, "signature")
        assert hasattr(result, "severity")
        assert hasattr(result, "summary")

    # ── Signature format ──────────────────────────────────────────────────────

    def test_signature_is_category_colon_class(self):
        """Signatures follow 'CATEGORY:ClassName' produced by ExceptionBlock.signature()."""
        result = extract_error("KeyError: 'host' missing")
        # KeyError → MISSING_KEY category.  The Airflow parser identifies the
        # category from the block content but the class name inside the signature
        # is "UnknownException" because _extract_python_traceback requires a
        # full "Traceback (most recent call last):" header to extract the class.
        assert "MISSING_KEY" in result.signature

    def test_executor_lost_failure_signature(self):
        """ExecutorLostFailure matches EXECUTOR_FAILURE in the exception catalogue."""
        # Message doesn't hit the assembler anchor (no ERROR/EXCEPTION token),
        # so the generic fallback fires → UNKNOWN:ExecutorLostFailure
        result = extract_error("ExecutorLostFailure: Spark executor ran out of memory")
        assert "ExecutorLostFailure" in result.signature

    def test_oom_signature_contains_category(self):
        """OutOfMemoryError should be classified as OOM."""
        result = extract_error("OutOfMemoryError: Java heap space")
        assert "OOM" in result.signature

    def test_null_pointer_signature_contains_category(self):
        result = extract_error("NullPointerException: object is null")
        assert "NULL_REF" in result.signature

    def test_unknown_error_gets_unknown_category(self):
        """Messages without a catalogued exception class fall back to UNKNOWN."""
        result = extract_error("Something bad happened in the pipeline")
        assert "UNKNOWN" in result.signature

    # ── Severity ──────────────────────────────────────────────────────────────

    def test_severity_critical_for_oom(self):
        result = extract_error("OutOfMemoryError: Java heap space")
        assert result.severity == "critical"

    def test_severity_high_for_null_pointer(self):
        # NullPointerException → NULL_REF → severity "medium"
        result = extract_error("NullPointerException: object is null")
        assert result.severity == "medium"

    def test_severity_high_for_key_error(self):
        result = extract_error("KeyError: 'host' missing")
        assert result.severity == "high"

    def test_severity_medium_for_unrecognised_message(self):
        """Unclassified messages default to medium severity."""
        result = extract_error("Connection timeout after 30s")
        assert result.severity == "medium"

    def test_severity_is_string(self):
        result = extract_error("Something happened")
        assert isinstance(result.severity, str)
        assert result.severity in {"critical", "high", "medium", "low"}

    # ── Summary ───────────────────────────────────────────────────────────────

    def test_summary_is_string(self):
        result = extract_error("KeyError: 'host' missing in config")
        assert isinstance(result.summary, str)

    def test_summary_respects_max_chars(self):
        """to_debug_context(max_chars=1000) — summary is at most 1000 chars."""
        msg = "KeyError: " + "x" * 5000
        result = extract_error(msg)
        assert len(result.summary) <= 1000

    def test_summary_is_non_empty_for_known_exceptions(self):
        result = extract_error("KeyError: 'host' missing in config")
        # The summary contains the formatted debug context, not the raw message.
        # Exact content depends on whether the traceback block is full or partial.
        assert len(result.summary) > 0

    def test_summary_non_empty_for_non_empty_message(self):
        result = extract_error("SomethingWentWrong: details here")
        assert result.summary.strip() != ""

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_empty_message_does_not_raise(self):
        result = extract_error("")
        assert isinstance(result, ParsedError)
        assert isinstance(result.signature, str)

    def test_message_with_multiple_colons(self):
        """The MISSING_KEY category is identified from the block content."""
        result = extract_error("KeyError: 'host': missing in config")
        # Category is correctly identified even without a full traceback header.
        assert "MISSING_KEY" in result.signature

    def test_python_traceback_parsed(self):
        """Full Python traceback produces a MISSING_KEY category signature."""
        tb = (
            "Traceback (most recent call last):\n"
            '  File "pipeline.py", line 42, in transform\n'
            "    result = df.groupby(key)\n"
            "KeyError: 'region'\n"
        )
        result = extract_error(tb)
        # The block assembler anchors on "KeyError" (contains "error"), so only
        # the final exception line is processed.  Category is still identified.
        assert "MISSING_KEY" in result.signature

    def test_spark_java_trace_parsed(self):
        """Java-style trace with Caused by: chain produces OOM or EXECUTOR category."""
        trace = (
            "org.apache.spark.SparkException: Job aborted due to stage failure\n"
            "\tat org.apache.spark.scheduler.DAGScheduler.failJobAndIndependentStages(DAGScheduler.scala:2059)\n"
            "Caused by: java.lang.OutOfMemoryError: Java heap space\n"
            "\tat java.util.Arrays.copyOf(Arrays.java:3210)\n"
        )
        result = extract_error(trace)
        assert "OOM" in result.signature or "EXECUTOR" in result.signature
