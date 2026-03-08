import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "root-cause-engine"))
from engine import rank_hypotheses


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
