from card_engine.detector import detect_card


class DummyImage:
    shape = (40, 20, 3)


def test_detector_placeholder_uses_shape():
    detection = detect_card(DummyImage())
    assert detection.bbox == (0, 0, 20, 40)
