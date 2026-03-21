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


def test_score_candidates_penalizes_ambiguous_same_name_printings():
    best_name, confidence = score_candidates(
        [
            Candidate(name="Evolving Wilds", score=0.86, set_code="EOC", collector_number="158", notes=["fuzzy", "layout_match"]),
            Candidate(name="Evolving Wilds", score=0.84, set_code="DRC", collector_number="154", notes=["fuzzy", "layout_match"]),
            Candidate(name="Evolving Wilds", score=0.82, set_code="IMA", collector_number="235", notes=["fuzzy", "layout_match"]),
            Candidate(name="Evolving Wilds", score=0.80, set_code="BRO", collector_number="261", notes=["fuzzy", "layout_match"]),
        ]
    )

    assert best_name == "Evolving Wilds"
    assert confidence < 0.9


def test_score_candidates_keeps_visual_confirmed_printing_confident():
    best_name, confidence = score_candidates(
        [
            Candidate(
                name="Evolving Wilds",
                score=0.8884,
                set_code="DRC",
                collector_number="154",
                notes=["fuzzy", "layout_match", "set_symbol_match", "art_match"],
            ),
            Candidate(
                name="Evolving Wilds",
                score=0.8615,
                set_code="EOC",
                collector_number="158",
                notes=["fuzzy", "layout_match", "set_symbol_match", "art_match"],
            ),
            Candidate(
                name="Evolving Wilds",
                score=0.8148,
                set_code="IMA",
                collector_number="235",
                notes=["fuzzy", "layout_match", "set_symbol_weak", "art_match"],
            ),
        ]
    )

    assert best_name == "Evolving Wilds"
    assert confidence > 0.9
