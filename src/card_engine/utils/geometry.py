TARGET_CARD_RATIO = 63 / 88


def aspect_ratio(width: int, height: int) -> float:
    if height == 0:
        return 0.0
    return width / height


def area(width: int, height: int) -> int:
    return max(0, width) * max(0, height)


def clamp_bbox(
    bbox: tuple[int, int, int, int],
    *,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int, int, int]:
    left, top, width, height = bbox
    left = max(0, min(left, frame_width))
    top = max(0, min(top, frame_height))
    width = max(0, min(width, frame_width - left))
    height = max(0, min(height, frame_height - top))
    return (left, top, width, height)


def centered_aspect_bbox(
    frame_width: int,
    frame_height: int,
    *,
    target_ratio: float = TARGET_CARD_RATIO,
    inset_ratio: float = 0.92,
) -> tuple[int, int, int, int]:
    usable_width = max(1, int(frame_width * inset_ratio))
    usable_height = max(1, int(frame_height * inset_ratio))

    if aspect_ratio(usable_width, usable_height) > target_ratio:
        height = usable_height
        width = max(1, int(round(height * target_ratio)))
    else:
        width = usable_width
        height = max(1, int(round(width / target_ratio)))

    left = max(0, (frame_width - width) // 2)
    top = max(0, (frame_height - height) // 2)
    return (left, top, width, height)
