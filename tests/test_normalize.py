from card_engine.normalize import normalize_card


def test_normalize_placeholder_passes_image_through():
    image = object()
    result = normalize_card(image, (0, 0, 1, 1))
    assert result.normalized_image is image
