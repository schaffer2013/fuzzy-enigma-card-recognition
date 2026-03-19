import re

_STRIP_TRANSLATIONS = str.maketrans(
    {
        "'": "",
        "’": "",
        "`": "",
        "´": "",
    }
)


def normalize_text(value: str) -> str:
    collapsed = re.sub(r"[^0-9a-z]+", " ", value.casefold().translate(_STRIP_TRANSLATIONS))
    return " ".join(collapsed.strip().split())
