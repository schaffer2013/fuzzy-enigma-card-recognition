from pathlib import Path


def load_image(path: str) -> bytes:
    return Path(path).read_bytes()
