from card_engine.models import Candidate
from card_engine.scorer import score_candidates


def test_score_candidates_uses_margin_and_notes_for_confidence():
    best_name, confidence = score_candidates(
        [
            Candidate(name="Lightning Bolt", score=0.86, notes=["exact", "type_line_match", "lower_text_match"]),
            Candidate(name="Chain Lightning", score=0.62, notes=["fuzzy"]),
        ]
    )

    assert best_name == "Lightning Bolt"
    assert confidence > 0.9


def test_score_candidates_penalizes_mismatch_notes():
    best_name, confidence = score_candidates(
        [
            Candidate(name="Opt", score=0.78, notes=["fuzzy", "type_line_mismatch", "layout_mismatch"]),
            Candidate(name="Optimus", score=0.5, notes=["fuzzy"]),
        ]
    )

    assert best_name == "Opt"
    assert confidence < 0.78
