from .models import Candidate


def score_candidates(candidates: list[Candidate]) -> tuple[str | None, float]:
    if not candidates:
        return None, 0.0

    best = max(candidates, key=lambda c: c.score)
    return best.name, best.score
