from pathlib import Path
import re
import time

from card_engine.art_prehash import (
    count_valid_cached_art_records,
    eligible_art_records,
    prehash_missing_art_records,
)
from card_engine.catalog.local_index import CatalogRecord


def test_eligible_art_records_filters_nonpaper_and_missing_images():
    records = [
        CatalogRecord(name="Opt", normalized_name="opt", set_code="XLN", collector_number="65", image_uri="https://img.example/opt.png", games=("paper",)),
        CatalogRecord(name="Arena Card", normalized_name="arena-card", set_code="YTEST", collector_number="1", image_uri="https://img.example/arena.png", games=("arena",)),
        CatalogRecord(name="No Image", normalized_name="no-image", set_code="TMP", collector_number="2", image_uri=None, games=("paper",)),
    ]

    eligible = eligible_art_records(records)

    assert [(record.name, record.set_code) for record in eligible] == [("Opt", "XLN")]


def test_prehash_missing_art_records_counts_and_reports_progress(monkeypatch, tmp_path):
    records = [
        CatalogRecord(name="Opt", normalized_name="opt", set_code="xln", collector_number="65", image_uri="https://img.example/opt.png", games=("paper",)),
        CatalogRecord(name="Shock", normalized_name="shock", set_code="m19", collector_number="156", image_uri="https://img.example/shock.png", games=("paper",)),
    ]
    cache_dir = tmp_path / "art_match_refs"
    progress_messages: list[str] = []

    def fake_load_or_compute(record, *, download_timeout_seconds=10.0, progress_callback=None):
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_name = f"{record.set_code}-{record.collector_number}.json"
        (cache_dir / cache_name).write_text(
            '{"fingerprint":{"gray_dhash":"a","edge_dhash":"b","hsv_histogram":[0.1],"mean_bgr":[1,2,3]},"roi_signature":"test"}',
            encoding="utf-8",
        )
        return {
            "gray_dhash": "a",
            "edge_dhash": "b",
            "hsv_histogram": [0.1],
            "mean_bgr": [1, 2, 3],
        }

    monkeypatch.setattr("card_engine.art_prehash._load_or_compute_reference_fingerprint", fake_load_or_compute)
    monkeypatch.setattr("card_engine.art_prehash._refresh_reference_cache_if_needed", lambda: None)
    monkeypatch.setattr(
        "card_engine.art_prehash._has_valid_cached_fingerprint",
        lambda record, *, cache_dir: (cache_dir / f"{record.set_code}-{record.collector_number}.json").exists(),
    )

    result = prehash_missing_art_records(
        records,
        cache_dir=cache_dir,
        max_workers=2,
        progress_callback=lambda progress: progress_messages.append(progress.message),
    )

    assert result.total_eligible == 2
    assert result.already_hashed == 0
    assert result.attempted == 2
    assert result.newly_hashed == 2
    assert result.failures == []
    assert len(progress_messages) == 2
    assert all("cards/s" in message for message in progress_messages)
    assert all(re.search(r"eta: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", message) for message in progress_messages)
    assert count_valid_cached_art_records(records, cache_dir=cache_dir) == 2


def test_prehash_missing_art_records_can_cancel_before_next_record(monkeypatch, tmp_path):
    records = [
        CatalogRecord(name="Opt", normalized_name="opt", set_code="xln", collector_number="65", image_uri="https://img.example/opt.png", games=("paper",)),
        CatalogRecord(name="Shock", normalized_name="shock", set_code="m19", collector_number="156", image_uri="https://img.example/shock.png", games=("paper",)),
    ]
    cache_dir = tmp_path / "art_match_refs"
    calls = {"count": 0}

    def fake_load_or_compute(record, *, download_timeout_seconds=10.0, progress_callback=None):
        calls["count"] += 1
        return {
            "gray_dhash": "a",
            "edge_dhash": "b",
            "hsv_histogram": [0.1],
            "mean_bgr": [1, 2, 3],
        }

    monkeypatch.setattr("card_engine.art_prehash._load_or_compute_reference_fingerprint", fake_load_or_compute)
    monkeypatch.setattr("card_engine.art_prehash._refresh_reference_cache_if_needed", lambda: None)
    monkeypatch.setattr("card_engine.art_prehash._has_valid_cached_fingerprint", lambda record, *, cache_dir: False)

    should_stop_calls = {"count": 0}

    def should_stop():
        should_stop_calls["count"] += 1
        return should_stop_calls["count"] > 1

    result = prehash_missing_art_records(
        records,
        cache_dir=cache_dir,
        max_workers=1,
        should_stop=should_stop,
    )

    assert calls["count"] == 1
    assert result.cancelled is True
    assert result.attempted == 1
    assert result.newly_hashed == 1


def test_prehash_missing_art_records_can_cancel_inflight_workers(monkeypatch, tmp_path):
    records = [
        CatalogRecord(name="Opt", normalized_name="opt", set_code="xln", collector_number="65", image_uri="https://img.example/opt.png", games=("paper",)),
        CatalogRecord(name="Shock", normalized_name="shock", set_code="m19", collector_number="156", image_uri="https://img.example/shock.png", games=("paper",)),
        CatalogRecord(name="Unsummon", normalized_name="unsummon", set_code="m10", collector_number="76", image_uri="https://img.example/unsummon.png", games=("paper",)),
    ]
    cache_dir = tmp_path / "art_match_refs"
    calls = {"count": 0}
    started_at = time.monotonic()

    def fake_load_or_compute(record, *, download_timeout_seconds=10.0, progress_callback=None, should_stop=None):
        calls["count"] += 1
        while should_stop is not None and not should_stop():
            time.sleep(0.01)
        return None

    monkeypatch.setattr("card_engine.art_prehash._load_or_compute_reference_fingerprint", fake_load_or_compute)
    monkeypatch.setattr("card_engine.art_prehash._refresh_reference_cache_if_needed", lambda: None)
    monkeypatch.setattr("card_engine.art_prehash._has_valid_cached_fingerprint", lambda record, *, cache_dir: False)

    def should_stop():
        return (time.monotonic() - started_at) >= 0.05

    result = prehash_missing_art_records(
        records,
        cache_dir=cache_dir,
        max_workers=2,
        should_stop=should_stop,
    )

    assert calls["count"] == 2
    assert result.cancelled is True
    assert result.attempted == 2
    assert result.newly_hashed == 0
