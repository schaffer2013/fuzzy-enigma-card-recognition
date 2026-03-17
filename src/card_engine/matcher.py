from .catalog.local_index import CatalogMatch, LocalCatalogIndex
from .models import Candidate


def match_candidates(
    ocr_lines: list[str],
    limit: int = 5,
    catalog: LocalCatalogIndex | None = None,
) -> list[Candidate]:
    if not ocr_lines:
        return []

    joined = " ".join(ocr_lines).strip()
    if not joined:
        return []

    if catalog is not None:
        matches = catalog.search_name(joined, limit=limit)
        if matches:
            return [_candidate_from_catalog_match(match) for match in matches]

    return [Candidate(name=joined, score=0.2, notes=["catalog_unavailable"])][:limit]


def _candidate_from_catalog_match(match: CatalogMatch) -> Candidate:
    return Candidate(
        name=match.record.name,
        score=match.score,
        set_code=match.record.set_code,
        collector_number=match.record.collector_number,
        notes=[match.match_type],
    )
