import numpy

from card_engine.catalog.local_index import CatalogRecord, LocalCatalogIndex
from card_engine.models import Candidate
from card_engine.normalize import CropRegion
from card_engine.set_symbol import rerank_candidates_by_set_symbol


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
