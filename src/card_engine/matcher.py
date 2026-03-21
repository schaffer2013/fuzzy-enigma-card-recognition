from __future__ import annotations

from difflib import SequenceMatcher

from .catalog.local_index import CatalogMatch, LocalCatalogIndex
from .models import Candidate
from .utils.text_normalize import normalize_text

TITLE_WEIGHT = 0.74
TYPE_LINE_WEIGHT = 0.10
LOWER_TEXT_WEIGHT = 0.13
LAYOUT_WEIGHT = 0.03
TYPE_LINE_MISMATCH_PENALTY = 0.08
LOWER_TEXT_MISMATCH_PENALTY = 0.05
LAYOUT_MISMATCH_PENALTY = 0.08
NOISY_TITLE_PENALTY = 0.04
FUZZY_PRINTING_EXPANSION_THRESHOLD = 0.84


def match_candidates(
    ocr_lines: list[str],
    limit: int = 5,
    catalog: LocalCatalogIndex | None = None,
    *,
    results_by_roi: dict[str, dict] | None = None,
    layout_hint: str | None = None,
) -> list[Candidate]:
    title_query = _select_title_query(ocr_lines, results_by_roi)
    if not title_query:
        return []

    type_line_query = _select_type_line_query(results_by_roi)
    lower_text_query = _select_lower_text_query(results_by_roi)

    if catalog is not None:
        matches = catalog.search_name(title_query, limit=max(limit * 3, limit))
        if matches:
            matches, expanded_for_printing_tiebreak = _expand_matches_for_printing_tiebreak(matches, catalog)
            reranked = [
                _candidate_from_catalog_match(
                    match,
                    title_query=title_query,
                    type_line_query=type_line_query,
                    lower_text_query=lower_text_query,
                    layout_hint=layout_hint,
                )
                for match in matches
            ]
            reranked.sort(key=lambda candidate: (-candidate.score, candidate.name))
            if any(match.match_type == "exact" for match in matches) or expanded_for_printing_tiebreak:
                return reranked
            return reranked[:limit]

    return [Candidate(name=title_query, score=0.2, notes=["catalog_unavailable", "title_only"])][:limit]


def _candidate_from_catalog_match(
    match: CatalogMatch,
    *,
    title_query: str,
    type_line_query: str | None,
    lower_text_query: str | None,
    layout_hint: str | None,
) -> Candidate:
    notes = [match.match_type]
    score = match.score * TITLE_WEIGHT

    record_type_line = match.record.type_line or ""
    if type_line_query and record_type_line:
        type_line_score = _compatibility_score(type_line_query, record_type_line)
        score += type_line_score * TYPE_LINE_WEIGHT
        if type_line_score >= 0.65:
            notes.append("type_line_match")
        elif type_line_score <= 0.2:
            score -= TYPE_LINE_MISMATCH_PENALTY
            notes.append("type_line_mismatch")

    lower_text_candidates = _record_lower_text_candidates(match.record)
    if lower_text_query and lower_text_candidates:
        lower_text_score = max(_compatibility_score(lower_text_query, candidate) for candidate in lower_text_candidates)
        score += lower_text_score * LOWER_TEXT_WEIGHT
        if lower_text_score >= 0.55:
            notes.append("lower_text_match")
        elif lower_text_score <= 0.12:
            score -= LOWER_TEXT_MISMATCH_PENALTY
            notes.append("lower_text_mismatch")

    if layout_hint and match.record.layout:
        if _layouts_compatible(layout_hint, match.record.layout):
            score += LAYOUT_WEIGHT
            notes.append("layout_match")
        else:
            score -= LAYOUT_MISMATCH_PENALTY
            notes.append("layout_mismatch")

    if _normalized_contains_noise(title_query):
        score -= NOISY_TITLE_PENALTY
        notes.append("noisy_title_ocr")

    return Candidate(
        name=match.record.name,
        score=max(0.0, min(1.0, round(score, 4))),
        set_code=match.record.set_code,
        collector_number=match.record.collector_number,
        notes=notes,
    )


def _select_title_query(ocr_lines: list[str], results_by_roi: dict[str, dict] | None) -> str:
    title_like_rois = ("standard", "split_left", "split_right", "adventure", "transform_back")

    for roi_name in title_like_rois:
        roi_lines = _roi_lines(results_by_roi, roi_name)
        candidate = _clean_title_query(roi_lines)
        if candidate:
            return candidate

    return _clean_title_query(ocr_lines)


def _select_type_line_query(results_by_roi: dict[str, dict] | None) -> str | None:
    lines = _roi_lines(results_by_roi, "type_line")
    joined = " ".join(lines).strip()
    return joined or None


def _select_lower_text_query(results_by_roi: dict[str, dict] | None) -> str | None:
    lines = _roi_lines(results_by_roi, "lower_text")
    joined = " ".join(lines).strip()
    return joined or None


def _roi_lines(results_by_roi: dict[str, dict] | None, roi_name: str) -> list[str]:
    if not results_by_roi:
        return []
    roi_result = results_by_roi.get(roi_name, {})
    lines = roi_result.get("lines", [])
    return [str(line) for line in lines if str(line).strip()]


def _clean_title_query(lines: list[str]) -> str:
    cleaned_lines: list[str] = []
    for line in lines:
        tokens = [token for token in line.split() if not _looks_like_mana_or_noise(token)]
        cleaned = " ".join(tokens).strip()
        if cleaned:
            cleaned_lines.append(cleaned)

    if not cleaned_lines:
        return ""

    candidate = " ".join(cleaned_lines[:2]).strip()
    return candidate


def _looks_like_mana_or_noise(token: str) -> bool:
    stripped = token.strip("()[]{}<>")
    if not stripped:
        return True
    if stripped.isdigit() and len(stripped) <= 2:
        return True
    return False


def _compatibility_score(query: str, candidate: str) -> float:
    normalized_query = normalize_text(query)
    normalized_candidate = normalize_text(candidate)
    if not normalized_query or not normalized_candidate:
        return 0.0

    token_overlap = _token_overlap(normalized_query, normalized_candidate)
    similarity = SequenceMatcher(None, normalized_query, normalized_candidate).ratio()
    return (similarity * 0.65) + (token_overlap * 0.35)


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _layouts_compatible(observed_layout: str, catalog_layout: str) -> bool:
    observed = observed_layout.lower()
    catalog = catalog_layout.lower()
    if observed == catalog:
        return True
    aliases = {
        "transform": {"modal_dfc"},
        "modal_dfc": {"transform"},
    }
    return catalog in aliases.get(observed, set())


def _normalized_contains_noise(value: str) -> bool:
    normalized = normalize_text(value)
    return any(token.isdigit() for token in normalized.split())


def _record_lower_text_candidates(record) -> list[str]:
    candidates: list[str] = []
    if record.oracle_text and record.oracle_text.strip():
        candidates.append(record.oracle_text.strip())
    if record.flavor_text and record.flavor_text.strip():
        candidates.append(record.flavor_text.strip())
    combined = " ".join(part.strip() for part in (record.oracle_text, record.flavor_text) if part and part.strip())
    if combined:
        candidates.append(combined)
    return candidates


def _expand_matches_for_printing_tiebreak(
    matches: list[CatalogMatch],
    catalog: LocalCatalogIndex,
) -> tuple[list[CatalogMatch], bool]:
    if not matches:
        return matches, False

    top_match = matches[0]
    if top_match.match_type != "fuzzy" or top_match.score < FUZZY_PRINTING_EXPANSION_THRESHOLD:
        return matches, False

    exact_printings = catalog.exact_lookup(top_match.record.name)
    if len(exact_printings) <= 1:
        return matches, False

    expanded = list(matches)
    seen = {
        (match.record.name, match.record.set_code, match.record.collector_number)
        for match in matches
    }
    for record in exact_printings:
        key = (record.name, record.set_code, record.collector_number)
        if key in seen:
            continue
        expanded.append(
            CatalogMatch(
                record=record,
                score=top_match.score,
                match_type=top_match.match_type,
            )
        )
        seen.add(key)
    return expanded, len(expanded) > len(matches)
