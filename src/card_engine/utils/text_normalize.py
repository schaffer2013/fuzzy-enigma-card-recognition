import re


def normalize_text(value: str) -> str:
    collapsed = re.sub(r"[^0-9a-z]+", " ", value.casefold())
    return " ".join(collapsed.strip().split())
