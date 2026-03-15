from card_engine.api import recognize_card


class DummyImage:
    shape = (100, 80, 3)


def test_recognize_card_returns_result_shape():
    result = recognize_card(DummyImage())
    assert result.bbox == (0, 0, 80, 100)
    assert result.active_roi == "standard"
