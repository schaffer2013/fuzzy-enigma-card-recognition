from card_engine.detector import detect_card


class DummyImage:
    shape = (40, 20, 3)


def test_detector_infers_centered_card_bbox_when_frame_ratio_is_off():
    detection = detect_card(DummyImage())
    assert detection.bbox == (1, 7, 18, 25)
    assert detection.debug["method"] == "centered_aspect_crop"


class HintImage:
    shape = (100, 80, 3)
    card_bbox = (8, 12, 63, 88)


def test_detector_prefers_explicit_card_bbox_hint():
    detection = detect_card(HintImage())

    assert detection.bbox == (8, 12, 63, 88)
    assert detection.debug["method"] == "explicit_bbox"


class QuadHintImage:
    shape = (120, 90, 3)
    card_quad = ((10, 8), (72, 12), (70, 101), (12, 96))


def test_detector_prefers_explicit_card_quad_hint():
    detection = detect_card(QuadHintImage())

    assert detection.quad == ((10, 8), (72, 12), (70, 101), (12, 96))
    assert detection.bbox == (10, 8, 62, 93)
    assert detection.debug["method"] == "explicit_quad"
