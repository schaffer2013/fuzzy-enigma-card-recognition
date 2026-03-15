from card_engine.matcher import match_candidates


def test_matcher_returns_empty_for_empty_lines():
    assert match_candidates([]) == []
