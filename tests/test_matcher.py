from card_engine.catalog.local_index import CatalogRecord, LocalCatalogIndex
from card_engine.matcher import match_candidates


def test_matcher_returns_empty_for_empty_lines():
    assert match_candidates([]) == []


def test_matcher_uses_catalog_for_exact_match():
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Lightning Bolt", normalized_name="", set_code="M11"),
            CatalogRecord(name="Counterspell", normalized_name="", set_code="2XM"),
        ]
    )

    candidates = match_candidates(["lightning bolt"], catalog=catalog)

    assert candidates[0].name == "Lightning Bolt"
    assert candidates[0].score == 1.0
    assert candidates[0].set_code == "M11"
    assert candidates[0].notes == ["exact"]


def test_matcher_falls_back_when_catalog_missing():
    candidates = match_candidates(["Lightning", "Bolt"])

    assert candidates[0].name == "Lightning Bolt"
    assert candidates[0].score == 0.2
    assert candidates[0].notes == ["catalog_unavailable"]
