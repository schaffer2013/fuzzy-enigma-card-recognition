from .models import Candidate

MAX_MARGIN_BONUS = 0.08
SAME_NAME_SCORE_WINDOW = 0.12
MAX_SAME_NAME_PENALTY = 0.16


def score_candidates(candidates: list[Candidate]) -> tuple[str | None, float]:
    if not candidates:
        return None, 0.0

    ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    best = ranked[0]
    runner_up = ranked[1].score if len(ranked) > 1 else 0.0
    margin = max(0.0, best.score - runner_up)
    notes = set(best.notes or [])

    confidence = best.score
    confidence += min(MAX_MARGIN_BONUS, margin * 0.24)
    if "exact" in notes:
        confidence += 0.05
    if "type_line_match" in notes:
        confidence += 0.03
    if "lower_text_match" in notes:
        confidence += 0.04
    if "set_symbol_match" in notes:
        confidence += 0.035
    if "art_match" in notes:
        confidence += 0.04
    if "layout_match" in notes:
        confidence += 0.02
    if "layout_mismatch" in notes:
        confidence -= 0.08
    if "type_line_mismatch" in notes:
        confidence -= 0.055
    if "lower_text_mismatch" in notes:
        confidence -= 0.04

    confidence -= _same_name_printing_penalty(best, ranked, notes)

    return best.name, max(0.0, min(1.0, round(confidence, 4)))


def _same_name_printing_penalty(best: Candidate, ranked: list[Candidate], notes: set[str]) -> float:
    nearby_same_name = [
        candidate
        for candidate in ranked[1:]
        if candidate.name == best.name
        and _is_distinct_printing(candidate, best)
        and (best.score - candidate.score) <= SAME_NAME_SCORE_WINDOW
    ]
    if not nearby_same_name:
        return 0.0

    penalty = min(MAX_SAME_NAME_PENALTY, 0.035 * len(nearby_same_name))

    if "set_symbol_match" in notes and "art_match" in notes:
        penalty *= 0.4
    elif "set_symbol_match" in notes or "art_match" in notes:
        penalty *= 0.65
    else:
        penalty += 0.035

    return round(penalty, 4)


def _is_distinct_printing(left: Candidate, right: Candidate) -> bool:
    return (
        left.set_code != right.set_code
        or left.collector_number != right.collector_number
    )
