def aspect_ratio(width: int, height: int) -> float:
    if height == 0:
        return 0.0
    return width / height
