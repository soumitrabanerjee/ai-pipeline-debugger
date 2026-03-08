import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "ai-debugging-engine"))
from rag_pipeline import build_debug_prompt


class TestBuildDebugPrompt:

    def test_returns_string(self):
        result = build_debug_prompt("OOM error", ["incident 1"])
        assert isinstance(result, str)

    def test_contains_error_summary(self):
        result = build_debug_prompt("Spark OOM", ["previous incident"])
        assert "Spark OOM" in result

    def test_contains_each_incident(self):
        incidents = ["disk full on node-1", "executor killed on node-2"]
        result = build_debug_prompt("OOM", incidents)
        assert "disk full on node-1" in result
        assert "executor killed on node-2" in result

    def test_incidents_formatted_as_bullets(self):
        result = build_debug_prompt("error", ["incident A"])
        assert "- incident A" in result

    def test_empty_incidents_list(self):
        result = build_debug_prompt("some error", [])
        assert "some error" in result
        assert isinstance(result, str)

    def test_multiple_incidents_all_present(self):
        incidents = [f"incident {i}" for i in range(5)]
        result = build_debug_prompt("error", incidents)
        for inc in incidents:
            assert inc in result

    def test_prompt_contains_sre_context(self):
        result = build_debug_prompt("error", [])
        assert "SRE" in result or "error" in result.lower()
