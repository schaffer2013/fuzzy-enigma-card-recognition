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
    assert candidates[0].score == 0.74
    assert candidates[0].set_code == "M11"
    assert candidates[0].notes == ["exact"]


def test_matcher_removes_simple_title_noise_before_lookup():
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Akroan Horse", normalized_name="", set_code="THS"),
        ]
    )

    candidates = match_candidates(["Akroan Horse", "4"], catalog=catalog)

    assert candidates[0].name == "Akroan Horse"
    assert "exact" in candidates[0].notes


def test_matcher_uses_type_line_to_rerank_candidates():
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Opt", normalized_name="", set_code="XLN", type_line="Instant"),
            CatalogRecord(name="Opt", normalized_name="", set_code="ALT", type_line="Sorcery"),
        ]
    )

    candidates = match_candidates(
        ["Opt"],
        catalog=catalog,
        results_by_roi={
            "standard": {"lines": ["Opt"]},
            "type_line": {"lines": ["Instant"]},
        },
    )

    assert candidates[0].set_code == "XLN"
    assert "type_line_match" in (candidates[0].notes or [])
    assert candidates[0].score > candidates[1].score


def test_matcher_uses_layout_hint_to_rerank_candidates():
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Fire // Ice", normalized_name="", set_code="DMR", layout="split", aliases=["Fire"]),
            CatalogRecord(name="Fire", normalized_name="", set_code="STD", layout="normal"),
        ]
    )

    candidates = match_candidates(
        ["Fire"],
        catalog=catalog,
        results_by_roi={"split_left": {"lines": ["Fire"]}},
        layout_hint="split",
    )

    assert candidates[0].name == "Fire // Ice"
    assert "layout_match" in (candidates[0].notes or [])


def test_matcher_uses_lower_text_to_separate_same_name_printings():
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name="Commander's Plate",
                normalized_name="",
                set_code="CMR",
                type_line="Artifact Equipment",
                oracle_text="Equip commander 3. Equip 5.",
                flavor_text="Not all beautiful things are fragile.",
            ),
            CatalogRecord(
                name="Commander's Plate",
                normalized_name="",
                set_code="SLD",
                type_line="Artifact Equipment",
                oracle_text="Equip commander 3. Equip 5.",
                flavor_text="Armor changes, but Iron Man endures.",
            ),
        ]
    )

    candidates = match_candidates(
        ["Commander's Plate"],
        catalog=catalog,
        results_by_roi={
            "standard": {"lines": ["Commander's Plate"]},
            "type_line": {"lines": ["Artifact Equipment"]},
            "lower_text": {"lines": ["Armor changes, but Iron Man endures."]},
        },
        layout_hint="normal",
    )

    assert candidates[0].set_code == "SLD"
    assert "lower_text_match" in (candidates[0].notes or [])
    assert candidates[0].score > candidates[1].score


def test_matcher_keeps_all_exact_same_name_printings_for_late_tiebreaks():
    records = [
        CatalogRecord(name="Evolving Wilds", normalized_name="", set_code=f"S{i:02d}", collector_number=str(i))
        for i in range(30)
    ]
    catalog = LocalCatalogIndex.from_records(records)

    candidates = match_candidates(["Evolving Wilds"], limit=5, catalog=catalog)

    assert len(candidates) == 30
    assert {candidate.set_code for candidate in candidates} == {f"S{i:02d}" for i in range(30)}


def test_matcher_expands_strong_fuzzy_match_to_all_same_name_printings():
    records = [
        CatalogRecord(name="Evolving Wilds", normalized_name="", set_code=f"S{i:02d}", collector_number=str(i))
        for i in range(30)
    ]
    records.append(CatalogRecord(name="Evolving Shores", normalized_name="", set_code="ALT", collector_number="1"))
    catalog = LocalCatalogIndex.from_records(records)

    candidates = match_candidates(["Evolving gWilds"], limit=5, catalog=catalog)

    assert len(candidates) == 30
    assert all(candidate.name == "Evolving Wilds" for candidate in candidates)


def test_matcher_falls_back_when_catalog_missing():
    candidates = match_candidates(["Lightning", "Bolt"])

    assert candidates[0].name == "Lightning Bolt"
    assert candidates[0].score == 0.2
    assert candidates[0].notes == ["catalog_unavailable", "title_only"]
