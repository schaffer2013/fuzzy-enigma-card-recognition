import numpy

from card_engine.art_match import _load_or_compute_reference_fingerprint, rerank_candidates_by_art
from card_engine.catalog.local_index import CatalogRecord, LocalCatalogIndex
from card_engine.models import Candidate
from card_engine.normalize import CropRegion


def test_rerank_candidates_by_art_boosts_more_similar_candidate(monkeypatch):
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Plains", normalized_name="", set_code="M13", collector_number="230", image_uri="https://img.example/m13.png"),
            CatalogRecord(name="Plains", normalized_name="", set_code="DOM", collector_number="250", image_uri="https://img.example/dom.png"),
        ]
    )
    observed_crop = CropRegion(
        label="art_box",
        bbox=(0, 0, 80, 60),
        shape=(60, 80, 3),
        image_array=numpy.zeros((60, 80, 3), dtype=numpy.uint8),
    )

    def fake_similarity(record, *, observed_fingerprint, progress_callback=None):
        return 0.94 if record.set_code == "DOM" else 0.58

    monkeypatch.setattr("card_engine.art_match._reference_similarity_for_record", fake_similarity)
    monkeypatch.setattr(
        "card_engine.art_match._compute_art_fingerprint",
        lambda *_args, **_kwargs: {
            "gray_dhash": "f" * 81,
            "edge_dhash": "f" * 81,
            "hsv_histogram": [0.1] * 96,
            "mean_bgr": [120.0, 115.0, 110.0],
        },
    )

    result = rerank_candidates_by_art(
        [
            Candidate(name="Plains", score=0.77, set_code="M13", collector_number="230", notes=["exact"]),
            Candidate(name="Plains", score=0.77, set_code="DOM", collector_number="250", notes=["exact"]),
        ],
        observed_crop=observed_crop,
        catalog=catalog,
    )

    assert result.debug["used"] is True
    assert result.candidates[0].set_code == "DOM"
    assert "art_match" in (result.candidates[0].notes or [])


def test_art_reference_cache_is_cleared_when_roi_signature_changes(monkeypatch, tmp_path):
    record = CatalogRecord(
        name="Opt",
        normalized_name="opt",
        set_code="xln",
        collector_number="65",
        image_uri="https://img.example/opt.png",
    )
    calls = {"downloads": 0}

    monkeypatch.setattr("card_engine.art_match.ART_MATCH_CACHE_DIR", tmp_path)
    monkeypatch.setattr("card_engine.art_match._current_roi_signature", lambda: "signature-a")
    monkeypatch.setattr(
        "card_engine.art_match._download_reference_image",
        lambda *_args, **_kwargs: type("Img", (), {"image_array": numpy.zeros((80, 60, 3), dtype=numpy.uint8), "width": 60, "height": 80})(),
    )
    monkeypatch.setattr(
        "card_engine.art_match.normalize_card",
        lambda image, bbox, *, quad=None, roi_groups=None: type(
            "Norm",
            (),
            {
                "crops": {
                    "art_match:primary": CropRegion(
                        label="primary",
                        bbox=(0, 0, 20, 20),
                        shape=(20, 20, 3),
                        image_array=numpy.zeros((20, 20, 3), dtype=numpy.uint8),
                    )
                }
            },
        )(),
    )

    def fake_compute(_image_array):
        calls["downloads"] += 1
        return {
            "gray_dhash": f"{calls['downloads']:081x}",
            "edge_dhash": "f" * 81,
            "hsv_histogram": [0.1] * 96,
            "mean_bgr": [120.0, 115.0, 110.0],
        }

    monkeypatch.setattr("card_engine.art_match._compute_art_fingerprint", fake_compute)

    first = _load_or_compute_reference_fingerprint(record)
    second = _load_or_compute_reference_fingerprint(record)
    assert first == second
    assert calls["downloads"] == 1

    monkeypatch.setattr("card_engine.art_match._current_roi_signature", lambda: "signature-b")
    third = _load_or_compute_reference_fingerprint(record)

    assert calls["downloads"] == 2
    assert third["gray_dhash"] != first["gray_dhash"]
