from card_engine.catalog.local_index import CatalogRecord, LocalCatalogIndex
from card_engine.operational_modes import CandidatePool, ExpectedCard, normalize_recognition_mode, resolve_operational_mode


def test_normalize_recognition_mode_defaults_to_default():
    assert normalize_recognition_mode(None) == "default"


def test_resolve_operational_mode_builds_small_pool_from_expected_card():
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Island", normalized_name="", set_code="M21", collector_number="264", layout="normal"),
            CatalogRecord(name="Island", normalized_name="", set_code="ELD", collector_number="254", layout="normal"),
            CatalogRecord(name="Forest", normalized_name="", set_code="M21", collector_number="274", layout="normal"),
        ]
    )

    resolved = resolve_operational_mode(
        catalog,
        mode="small_pool",
        expected_card=ExpectedCard(name="Island"),
    )

    assert resolved.requested_mode == "small_pool"
    assert resolved.effective_mode == "small_pool"
    assert resolved.skip_secondary_ocr is True
    assert len(resolved.catalog.records) == 2


def test_resolve_operational_mode_uses_candidate_pool_for_small_pool():
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Island", normalized_name="", set_code="M21", collector_number="264", layout="normal"),
            CatalogRecord(name="Forest", normalized_name="", set_code="M21", collector_number="274", layout="normal"),
        ]
    )
    pool = CandidatePool.from_records(catalog.exact_lookup("Forest"))

    resolved = resolve_operational_mode(catalog, mode="small_pool", candidate_pool=pool)

    assert len(resolved.catalog.records) == 1
    assert resolved.catalog.records[0].name == "Forest"


def test_resolve_operational_mode_configures_real_reevaluation_mode():
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Opt", normalized_name="", set_code="XLN", collector_number="65", layout="normal"),
        ]
    )

    resolved = resolve_operational_mode(
        catalog,
        mode="reevaluation",
        expected_card=ExpectedCard(name="Opt"),
    )

    assert resolved.requested_mode == "reevaluation"
    assert resolved.effective_mode == "reevaluation"
    assert "disagreement recovery" in resolved.implementation_note
