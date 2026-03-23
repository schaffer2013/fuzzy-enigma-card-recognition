import numpy

from card_engine.catalog.local_index import CatalogRecord, LocalCatalogIndex
from card_engine.models import Candidate
from card_engine.normalize import CropRegion
from card_engine.set_symbol import _load_or_compute_reference_hash, rerank_candidates_by_set_symbol


def test_rerank_candidates_by_set_symbol_boosts_more_similar_candidate(monkeypatch):
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Commander's Plate", normalized_name="", set_code="CMR", collector_number="305", image_uri="https://img.example/cmr.png"),
            CatalogRecord(name="Commander's Plate", normalized_name="", set_code="SLD", collector_number="1733", image_uri="https://img.example/sld.png"),
        ]
    )
    observed_crop = CropRegion(
        label="set_symbol",
        bbox=(0, 0, 40, 40),
        shape=(40, 40, 3),
        image_array=numpy.zeros((40, 40, 3), dtype=numpy.uint8),
    )

    def fake_similarity(record, *, observed_fingerprint, progress_callback=None):
        return 0.96 if record.set_code == "SLD" else 0.51

    monkeypatch.setattr("card_engine.set_symbol._reference_similarity_for_record", fake_similarity)
    monkeypatch.setattr(
        "card_engine.set_symbol._compute_symbol_fingerprint",
        lambda *_args, **_kwargs: {
            "gray_dhash": "f" * 64,
            "edge_ahash": "f" * 64,
            "binary_mask": "f" * 576,
            "foreground_ratio": 0.5,
        },
    )

    result = rerank_candidates_by_set_symbol(
        [
            Candidate(name="Commander's Plate", score=0.82, set_code="CMR", collector_number="305", notes=["exact"]),
            Candidate(name="Commander's Plate", score=0.82, set_code="SLD", collector_number="1733", notes=["exact"]),
        ],
        observed_crop=observed_crop,
        catalog=catalog,
    )

    assert result.debug["used"] is True
    assert result.candidates[0].set_code == "SLD"
    assert "set_symbol_match" in (result.candidates[0].notes or [])


def test_rerank_candidates_by_set_symbol_considers_near_tied_same_name_candidates(monkeypatch):
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Canopy Spider", normalized_name="", set_code="10e", collector_number="254", image_uri="https://img.example/10e.png"),
            CatalogRecord(name="Canopy Spider", normalized_name="", set_code="m20", collector_number="339", image_uri="https://img.example/m20.png"),
            CatalogRecord(name="Canopy Spider", normalized_name="", set_code="8ed", collector_number="236", image_uri="https://img.example/8ed.png"),
            CatalogRecord(name="Canopy Spider", normalized_name="", set_code="7ed", collector_number="234", image_uri="https://img.example/7ed.png"),
        ]
    )
    observed_crop = CropRegion(
        label="set_symbol",
        bbox=(0, 0, 40, 40),
        shape=(40, 40, 3),
        image_array=numpy.zeros((40, 40, 3), dtype=numpy.uint8),
    )

    similarities = {"10e": 0.70, "m20": 0.69, "8ed": 0.95, "7ed": 0.51}

    def fake_similarity(record, *, observed_fingerprint, progress_callback=None):
        return similarities[record.set_code]

    monkeypatch.setattr("card_engine.set_symbol._reference_similarity_for_record", fake_similarity)
    monkeypatch.setattr(
        "card_engine.set_symbol._compute_symbol_fingerprint",
        lambda *_args, **_kwargs: {
            "gray_dhash": "f" * 64,
            "edge_ahash": "f" * 64,
            "binary_mask": "f" * 576,
            "foreground_ratio": 0.5,
        },
    )

    result = rerank_candidates_by_set_symbol(
        [
            Candidate(name="Canopy Spider", score=0.82, set_code="10e", collector_number="254", notes=["fuzzy"]),
            Candidate(name="Canopy Spider", score=0.81, set_code="m20", collector_number="339", notes=["fuzzy"]),
            Candidate(name="Canopy Spider", score=0.79, set_code="7ed", collector_number="234", notes=["fuzzy"]),
            Candidate(name="Canopy Spider", score=0.78, set_code="8ed", collector_number="236", notes=["fuzzy"]),
        ],
        observed_crop=observed_crop,
        catalog=catalog,
    )

    assert result.debug["used"] is True
    assert result.candidates[0].set_code == "8ed"


def test_rerank_candidates_by_set_symbol_does_not_drop_late_near_tied_candidate(monkeypatch):
    records = [
        CatalogRecord(name="Path to Exile", normalized_name="", set_code="md1", collector_number="3", image_uri="https://img.example/md1.png"),
        CatalogRecord(name="Path to Exile", normalized_name="", set_code="mm3", collector_number="17", image_uri="https://img.example/mm3.png"),
        CatalogRecord(name="Path to Exile", normalized_name="", set_code="mkc", collector_number="78", image_uri="https://img.example/mkc.png"),
        CatalogRecord(name="Path to Exile", normalized_name="", set_code="plst", collector_number="CON-15", image_uri="https://img.example/plst-con15.png"),
        CatalogRecord(name="Path to Exile", normalized_name="", set_code="ss2", collector_number="3", image_uri="https://img.example/ss2.png"),
        CatalogRecord(name="Path to Exile", normalized_name="", set_code="e02", collector_number="3", image_uri="https://img.example/e02.png"),
    ]
    catalog = LocalCatalogIndex.from_records(records)
    observed_crop = CropRegion(
        label="set_symbol",
        bbox=(0, 0, 40, 40),
        shape=(40, 40, 3),
        image_array=numpy.zeros((40, 40, 3), dtype=numpy.uint8),
    )

    similarities = {"md1": 0.75, "mm3": 0.76, "mkc": 0.77, "plst": 0.60, "ss2": 0.69, "e02": 0.98}

    def fake_similarity(record, *, observed_fingerprint, progress_callback=None):
        return similarities[record.set_code]

    monkeypatch.setattr("card_engine.set_symbol._reference_similarity_for_record", fake_similarity)
    monkeypatch.setattr(
        "card_engine.set_symbol._compute_symbol_fingerprint",
        lambda *_args, **_kwargs: {
            "gray_dhash": "f" * 64,
            "edge_ahash": "f" * 64,
            "binary_mask": "f" * 576,
            "foreground_ratio": 0.5,
        },
    )

    result = rerank_candidates_by_set_symbol(
        [
            Candidate(name="Path to Exile", score=0.7646, set_code="md1", collector_number="3", notes=["fuzzy"]),
            Candidate(name="Path to Exile", score=0.7646, set_code="mm3", collector_number="17", notes=["fuzzy"]),
            Candidate(name="Path to Exile", score=0.7646, set_code="mkc", collector_number="78", notes=["fuzzy"]),
            Candidate(name="Path to Exile", score=0.7646, set_code="plst", collector_number="CON-15", notes=["fuzzy"]),
            Candidate(name="Path to Exile", score=0.7646, set_code="ss2", collector_number="3", notes=["fuzzy"]),
            Candidate(name="Path to Exile", score=0.7646, set_code="e02", collector_number="3", notes=["fuzzy"]),
        ],
        observed_crop=observed_crop,
        catalog=catalog,
    )

    assert result.debug["used"] is True
    assert result.candidates[0].set_code == "e02"


def test_set_symbol_reference_cache_is_cleared_when_roi_signature_changes(monkeypatch, tmp_path):
    record = CatalogRecord(
        name="Opt",
        normalized_name="opt",
        set_code="xln",
        collector_number="65",
        image_uri="https://img.example/opt.png",
    )
    calls = {"downloads": 0}

    monkeypatch.setattr("card_engine.set_symbol.SET_SYMBOL_CACHE_DIR", tmp_path)
    monkeypatch.setattr("card_engine.set_symbol._current_roi_signature", lambda: "signature-a")
    monkeypatch.setattr(
        "card_engine.set_symbol._download_reference_image",
        lambda *_args, **_kwargs: type("Img", (), {"image_array": numpy.zeros((80, 60, 3), dtype=numpy.uint8), "width": 60, "height": 80})(),
    )
    monkeypatch.setattr(
        "card_engine.set_symbol.normalize_card",
        lambda image, bbox, *, quad=None, roi_groups=None: type(
            "Norm",
            (),
            {
                "crops": {
                    "set_symbol:primary": CropRegion(
                        label="primary",
                        bbox=(0, 0, 10, 10),
                        shape=(10, 10, 3),
                        image_array=numpy.zeros((10, 10, 3), dtype=numpy.uint8),
                    )
                }
            },
        )(),
    )

    def fake_compute(_image_array):
        calls["downloads"] += 1
        return {
            "gray_dhash": f"{calls['downloads']:064x}",
            "edge_ahash": "f" * 64,
            "binary_mask": "f" * 576,
            "foreground_ratio": 0.5,
        }

    monkeypatch.setattr("card_engine.set_symbol._compute_symbol_fingerprint", fake_compute)

    first = _load_or_compute_reference_hash(record)
    second = _load_or_compute_reference_hash(record)
    assert first == second
    assert calls["downloads"] == 1

    monkeypatch.setattr("card_engine.set_symbol._current_roi_signature", lambda: "signature-b")
    third = _load_or_compute_reference_hash(record)

    assert calls["downloads"] == 2
    assert third["gray_dhash"] != first["gray_dhash"]
