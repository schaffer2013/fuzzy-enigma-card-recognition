from .models import Candidate


def score_candidates(candidates: list[Candidate]) -> tuple[str | None, float]:
    if not candidates:
        return None, 0.0

    ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    best = ranked[0]
    runner_up = ranked[1].score if len(ranked) > 1 else 0.0
    margin = max(0.0, best.score - runner_up)

    confidence = best.score
    confidence += min(0.12, margin * 0.35)
    if best.notes and "exact" in best.notes:
        confidence += 0.06
    if best.notes and "type_line_match" in best.notes:
        confidence += 0.04
    if best.notes and "lower_text_match" in best.notes:
        confidence += 0.05
    if best.notes and "set_symbol_match" in best.notes:
        confidence += 0.05
    if best.notes and "art_match" in best.notes:
        confidence += 0.05
    if best.notes and "layout_match" in best.notes:
        confidence += 0.03
    if best.notes and "layout_mismatch" in best.notes:
        confidence -= 0.08
    if best.notes and "type_line_mismatch" in best.notes:
        confidence -= 0.06
    if best.notes and "lower_text_mismatch" in best.notes:
        confidence -= 0.04

    return best.name, max(0.0, min(1.0, round(confidence, 4)))
