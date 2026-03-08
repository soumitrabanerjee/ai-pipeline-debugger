import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "log-processing-layer"))
from parser import extract_error, ParsedError


class TestExtractError:

    def test_returns_parsed_error_dataclass(self):
        result = extract_error("SomeError: something went wrong")
        assert isinstance(result, ParsedError)

    def test_signature_split_on_colon(self):
        result = extract_error("ExecutorLostFailure: Spark executor ran out of memory")
        assert result.signature == "ExecutorLostFailure"

    def test_signature_truncated_at_60_chars_when_no_colon(self):
        msg = "A" * 100
        result = extract_error(msg)
        assert result.signature == "A" * 60

    def test_severity_high_when_exception_in_message(self):
        result = extract_error("NullPointerException: something blew up")
        assert result.severity == "high"

    def test_severity_high_when_error_keyword_in_message(self):
        result = extract_error("This is an ERROR log line")
        assert result.severity == "high"

    def test_severity_medium_for_normal_message(self):
        result = extract_error("Connection timeout after 30s")
        assert result.severity == "medium"

    def test_summary_is_first_200_chars(self):
        msg = "X" * 300
        result = extract_error(msg)
        assert result.summary == "X" * 200

    def test_summary_short_message_unchanged(self):
        msg = "Short error message"
        result = extract_error(msg)
        assert result.summary == msg

    def test_empty_message(self):
        result = extract_error("")
        assert result.signature == ""
        assert result.severity == "medium"
        assert result.summary == ""

    def test_message_with_multiple_colons_uses_first(self):
        result = extract_error("KeyError: 'host': missing in config")
        assert result.signature == "KeyError"
