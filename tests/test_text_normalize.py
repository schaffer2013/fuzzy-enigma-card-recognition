from card_engine.utils.text_normalize import normalize_text


def test_normalize_text_collapses_spacing_case_and_punctuation():
    assert normalize_text("  Nicol Bolas,   Dragon-God  ") == "nicol bolas dragon god"
