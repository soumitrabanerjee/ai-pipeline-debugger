def rank_hypotheses(candidates: list[dict]) -> list[dict]:
    return sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)
