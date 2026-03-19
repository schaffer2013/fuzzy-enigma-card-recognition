from card_engine.utils.text_normalize import normalize_text


def test_normalize_text_collapses_spacing_case_and_punctuation():
    assert normalize_text("  Nicol Bolas,   Dragon-God  ") == "nicol bolas dragon god"


def test_normalize_text_strips_apostrophes_without_splitting_words():
    assert normalize_text("Urza's Saga") == "urzas saga"
