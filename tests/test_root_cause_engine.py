import sys
import os
import pytest
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "root-cause-engine"))
from engine import rank_hypotheses, build_hypotheses, select_top, _RULE_CATALOGUE


# ── Helpers ────────────────────────────────────────────────────────────────────

@dataclass
class FakeParsed:
    """Minimal stand-in for parser.ParsedError."""
    signature: str
    severity: str = "medium"
    summary: str = ""


AI_SUCCESS = {
    "root_cause":     "Spark executor ran out of memory.",
    "suggested_fix":  "Increase spark.executor.memory to 8g.",
    "confidence_score": 0.95,
}

AI_LOW_CONF = {
    "root_cause":     "Possible memory issue.",
    "suggested_fix":  "Check memory settings.",
    "confidence_score": 0.40,
}

AI_FALLBACK = {
    "root_cause":     "Analysis Failed (AI Service Unavailable)",
    "suggested_fix":  "Check logs manually.",
}

AI_UNAVAILABLE = {
    "root_cause":     "Service unavailable",
    "suggested_fix":  "Retry later.",
}


# ── rank_hypotheses ────────────────────────────────────────────────────────────

class TestRankHypotheses:

    def test_returns_list(self):
        result = rank_hypotheses([{"hypothesis": "A", "score": 0.5}])
        assert isinstance(result, list)

    def test_sorted_descending_by_score(self):
        candidates = [
            {"hypothesis": "A", "score": 0.3},
            {"hypothesis": "B", "score": 0.9},
            {"hypothesis": "C", "score": 0.6},
        ]
        result = rank_hypotheses(candidates)
        scores = [c["score"] for c in result]
        assert scores == [0.9, 0.6, 0.3]

    def test_empty_list(self):
        assert rank_hypotheses([]) == []

    def test_single_item(self):
        candidates = [{"hypothesis": "only one", "score": 0.8}]
        result = rank_hypotheses(candidates)
        assert result == candidates

    def test_missing_score_defaults_to_zero(self):
        candidates = [
            {"hypothesis": "no score"},
            {"hypothesis": "has score", "score": 0.5},
        ]
        result = rank_hypotheses(candidates)
        assert result[0]["hypothesis"] == "has score"
        assert result[1]["hypothesis"] == "no score"

    def test_equal_scores_preserves_all_items(self):
        candidates = [
            {"hypothesis": "A", "score": 0.5},
            {"hypothesis": "B", "score": 0.5},
        ]
        result = rank_hypotheses(candidates)
        assert len(result) == 2

    def test_does_not_mutate_original_list(self):
        candidates = [
            {"hypothesis": "A", "score": 0.1},
            {"hypothesis": "B", "score": 0.9},
        ]
        original_first = candidates[0]["hypothesis"]
        rank_hypotheses(candidates)
        assert candidates[0]["hypothesis"] == original_first


# ── build_hypotheses ───────────────────────────────────────────────────────────

class TestBuildHypothesesAiSource:

    def test_includes_ai_hypothesis_on_success(self):
        parsed = FakeParsed("UNKNOWN:SomeError")
        result = build_hypotheses(AI_SUCCESS, parsed)
        ai = next((h for h in result if h["source"] == "ai"), None)
        assert ai is not None
        assert ai["hypothesis"] == AI_SUCCESS["root_cause"]
        assert ai["fix"] == AI_SUCCESS["suggested_fix"]
        assert ai["score"] == 0.95

    def test_excludes_ai_hypothesis_when_unavailable(self):
        parsed = FakeParsed("UNKNOWN:SomeError")
        result = build_hypotheses(AI_UNAVAILABLE, parsed)
        sources = [h["source"] for h in result]
        assert "ai" not in sources

    def test_excludes_ai_hypothesis_when_analysis_failed(self):
        parsed = FakeParsed("UNKNOWN:SomeError")
        result = build_hypotheses(AI_FALLBACK, parsed)
        sources = [h["source"] for h in result]
        assert "ai" not in sources

    def test_excludes_ai_hypothesis_when_root_cause_empty(self):
        parsed = FakeParsed("UNKNOWN:SomeError")
        result = build_hypotheses({"root_cause": "", "suggested_fix": "x"}, parsed)
        sources = [h["source"] for h in result]
        assert "ai" not in sources

    def test_defaults_confidence_score_to_0_5_when_missing(self):
        parsed = FakeParsed("UNKNOWN:SomeError")
        ai = {"root_cause": "Something happened.", "suggested_fix": "Fix it."}
        result = build_hypotheses(ai, parsed)
        ai_h = next(h for h in result if h["source"] == "ai")
        assert ai_h["score"] == 0.5

    def test_handles_none_ai_result(self):
        # Should not raise, should return only rule hypothesis or empty list
        result = build_hypotheses(None, FakeParsed("UNKNOWN:SomeError"))
        assert isinstance(result, list)


class TestBuildHypothesesRuleSource:

    def test_includes_rule_hypothesis_for_known_category(self):
        parsed = FakeParsed("OOM:OutOfMemoryError")
        result = build_hypotheses(AI_FALLBACK, parsed)
        rule = next((h for h in result if h["source"] == "rule"), None)
        assert rule is not None
        assert rule["score"] == _RULE_CATALOGUE["OOM"]["score"]
        assert "memory" in rule["hypothesis"].lower()

    def test_no_rule_hypothesis_for_unknown_category(self):
        parsed = FakeParsed("UNKNOWN:SomeError")
        result = build_hypotheses(AI_FALLBACK, parsed)
        sources = [h["source"] for h in result]
        assert "rule" not in sources

    def test_no_rule_hypothesis_when_parsed_is_none(self):
        result = build_hypotheses(AI_SUCCESS, None)
        sources = [h["source"] for h in result]
        assert "rule" not in sources

    def test_both_hypotheses_present_when_ai_succeeds_and_category_known(self):
        parsed = FakeParsed("OOM:OutOfMemoryError")
        result = build_hypotheses(AI_SUCCESS, parsed)
        sources = {h["source"] for h in result}
        assert "ai" in sources
        assert "rule" in sources

    def test_returns_list_of_dicts(self):
        result = build_hypotheses(AI_SUCCESS, FakeParsed("OOM:OutOfMemoryError"))
        assert all(isinstance(h, dict) for h in result)
        for h in result:
            assert "source" in h
            assert "hypothesis" in h
            assert "fix" in h
            assert "score" in h


# ── select_top ─────────────────────────────────────────────────────────────────

class TestSelectTop:

    def test_returns_none_for_empty_list(self):
        assert select_top([]) is None

    def test_returns_highest_scoring_candidate(self):
        candidates = [
            {"source": "ai",   "hypothesis": "A", "fix": "", "score": 0.95},
            {"source": "rule", "hypothesis": "B", "fix": "", "score": 0.82},
        ]
        top = select_top(candidates)
        assert top["source"] == "ai"
        assert top["score"] == 0.95

    def test_rule_wins_when_ai_confidence_is_lower(self):
        candidates = [
            {"source": "ai",   "hypothesis": "Maybe OOM",   "fix": "", "score": 0.40},
            {"source": "rule", "hypothesis": "Definite OOM", "fix": "", "score": 0.82},
        ]
        top = select_top(candidates)
        assert top["source"] == "rule"

    def test_single_candidate_is_returned(self):
        c = {"source": "rule", "hypothesis": "X", "fix": "Y", "score": 0.75}
        assert select_top([c]) == c

    def test_does_not_mutate_input(self):
        candidates = [
            {"source": "ai",   "hypothesis": "A", "fix": "", "score": 0.9},
            {"source": "rule", "hypothesis": "B", "fix": "", "score": 0.8},
        ]
        original_order = [c["source"] for c in candidates]
        select_top(candidates)
        assert [c["source"] for c in candidates] == original_order


# ── Rule catalogue coverage ────────────────────────────────────────────────────

class TestRuleCatalogue:

    ALL_CATEGORIES = [
        "OOM", "BROADCAST_OOM", "EXECUTOR_FAILURE", "DATA_TYPE",
        "MISSING_KEY", "MISSING_FILE", "SCHEMA_MISMATCH", "NETWORK",
        "IO_ERROR", "TIMEOUT", "NULL_REF", "PERMISSIONS", "CLASSPATH",
        "DIVIDE_BY_ZERO", "AIRFLOW_INTERNAL", "ENCODING", "ASSERTION",
    ]

    def test_catalogue_has_all_expected_categories(self):
        for cat in self.ALL_CATEGORIES:
            assert cat in _RULE_CATALOGUE, f"Missing category: {cat}"

    def test_every_entry_has_required_keys(self):
        for cat, entry in _RULE_CATALOGUE.items():
            assert "hypothesis" in entry, f"{cat} missing 'hypothesis'"
            assert "fix"        in entry, f"{cat} missing 'fix'"
            assert "score"      in entry, f"{cat} missing 'score'"

    def test_all_scores_below_0_9_so_high_confidence_ai_wins(self):
        for cat, entry in _RULE_CATALOGUE.items():
            assert entry["score"] < 0.9, (
                f"{cat} score {entry['score']} >= 0.9 — "
                "would beat a high-confidence AI result"
            )

    def test_all_scores_above_0_5(self):
        for cat, entry in _RULE_CATALOGUE.items():
            assert entry["score"] > 0.5, f"{cat} score {entry['score']} too low"

    def test_oom_hypothesis_mentions_memory(self):
        assert "memory" in _RULE_CATALOGUE["OOM"]["hypothesis"].lower()

    def test_executor_failure_hypothesis_mentions_executor(self):
        assert "executor" in _RULE_CATALOGUE["EXECUTOR_FAILURE"]["hypothesis"].lower()

    def test_schema_mismatch_fix_mentions_schema(self):
        assert "schema" in _RULE_CATALOGUE["SCHEMA_MISMATCH"]["fix"].lower()


# ── End-to-end: build → select ─────────────────────────────────────────────────

class TestBuildAndSelectIntegration:

    def test_high_confidence_ai_beats_oom_rule(self):
        """A 0.95-confidence Claude result should win over the 0.82 OOM rule."""
        parsed = FakeParsed("OOM:OutOfMemoryError")
        candidates = build_hypotheses(AI_SUCCESS, parsed)
        top = select_top(candidates)
        assert top["source"] == "ai"

    def test_low_confidence_ai_loses_to_oom_rule(self):
        """A 0.40-confidence Claude result should lose to the 0.82 OOM rule."""
        parsed = FakeParsed("OOM:OutOfMemoryError")
        candidates = build_hypotheses(AI_LOW_CONF, parsed)
        top = select_top(candidates)
        assert top["source"] == "rule"

    def test_fallback_ai_with_known_category_returns_rule(self):
        """When AI is unavailable, the rule hypothesis should surface."""
        parsed = FakeParsed("NETWORK:ConnectionError")
        candidates = build_hypotheses(AI_FALLBACK, parsed)
        top = select_top(candidates)
        assert top is not None
        assert top["source"] == "rule"

    def test_fallback_ai_with_unknown_category_returns_none(self):
        """When AI is unavailable and no rule matches, select_top returns None."""
        parsed = FakeParsed("UNKNOWN:SomeError")
        candidates = build_hypotheses(AI_FALLBACK, parsed)
        assert select_top(candidates) is None

    def test_top_hypothesis_has_all_required_fields(self):
        parsed = FakeParsed("OOM:OutOfMemoryError")
        candidates = build_hypotheses(AI_SUCCESS, parsed)
        top = select_top(candidates)
        assert top is not None
        assert "source" in top
        assert "hypothesis" in top
        assert "fix" in top
        assert "score" in top
