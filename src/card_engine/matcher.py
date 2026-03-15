from .models import Candidate


def match_candidates(ocr_lines: list[str], limit: int = 5) -> list[Candidate]:
    """Placeholder candidate matcher.

    Returns no candidates when OCR output is empty.
    """
    if not ocr_lines:
        return []

    joined = " ".join(ocr_lines).strip()
    if not joined:
        return []

    return [Candidate(name=joined, score=0.2)][:limit]
