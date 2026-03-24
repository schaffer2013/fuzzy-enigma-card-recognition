from card_engine.catalog.local_index import CatalogRecord, LocalCatalogIndex
from card_engine.models import Candidate, RecognitionResult
from card_engine.operational_modes import ExpectedCard
from card_engine.session import RecognitionSession


class DummyImage:
    shape = (100, 80, 3)


def test_session_tracks_greenfield_results_when_enabled(monkeypatch):
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name="Opt",
                normalized_name="",
                scryfall_id="opt-1",
                oracle_id="oracle-opt",
                set_code="XLN",
                collector_number="65",
                layout="normal",
            ),
        ]
    )

    def fake_recognize_card(image, **kwargs):
        return RecognitionResult(
            bbox=(0, 0, 80, 100),
            best_name="Opt",
            confidence=0.96,
            top_k_candidates=[
                Candidate(
                    name="Opt",
                    score=0.94,
                    scryfall_id="opt-1",
                    oracle_id="oracle-opt",
                    set_code="XLN",
                    collector_number="65",
                ),
            ],
        )

    monkeypatch.setattr("card_engine.session.recognize_card", fake_recognize_card)

    session = RecognitionSession(catalog=catalog, auto_track_results=True)
    session.recognize(DummyImage(), mode="greenfield")

    entries = session.get_tracked_pool_entries()
    assert len(entries) == 1
    assert entries[0].name == "Opt"
    assert entries[0].scryfall_id == "opt-1"
    assert entries[0].oracle_id == "oracle-opt"
    assert entries[0].set_code == "XLN"


def test_session_small_pool_uses_tracked_pool_by_default(monkeypatch):
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Island", normalized_name="", set_code="M21", collector_number="264", layout="normal"),
            CatalogRecord(name="Forest", normalized_name="", set_code="M21", collector_number="274", layout="normal"),
        ]
    )
    seen_candidate_count = 0

    def fake_recognize_card(image, **kwargs):
        nonlocal seen_candidate_count
        pool = kwargs.get("candidate_pool")
        seen_candidate_count = len(pool.records) if pool is not None else -1
        return RecognitionResult(
            bbox=(0, 0, 80, 100),
            best_name="Island",
            confidence=0.93,
            top_k_candidates=[
                Candidate(name="Island", score=0.9, set_code="M21", collector_number="264"),
            ],
        )

    monkeypatch.setattr("card_engine.session.recognize_card", fake_recognize_card)

    session = RecognitionSession(catalog=catalog)
    assert session.add_expected_card(ExpectedCard(name="Island", set_code="M21", collector_number="264")) is True

    session.recognize(DummyImage(), mode="small_pool")

    assert seen_candidate_count == 1


def test_session_clear_tracked_pool_resets_entries():
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Island", normalized_name="", set_code="M21", collector_number="264", layout="normal"),
        ]
    )
    session = RecognitionSession(catalog=catalog)

    assert session.add_expected_card(ExpectedCard(name="Island", set_code="M21", collector_number="264")) is True
    assert len(session.get_tracked_pool_entries()) == 1

    session.clear_tracked_pool()

    assert session.get_tracked_pool_entries() == []


def test_session_small_pool_requires_available_pool(monkeypatch):
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Island", normalized_name="", set_code="M21", collector_number="264", layout="normal"),
        ]
    )
    monkeypatch.setattr("card_engine.session.recognize_card", lambda image, **kwargs: None)
    session = RecognitionSession(catalog=catalog)

    try:
        session.recognize(DummyImage(), mode="small_pool")
    except ValueError as exc:
        assert "No tracked pool" in str(exc)
    else:
        raise AssertionError("Expected small_pool session call without tracked pool to fail")
