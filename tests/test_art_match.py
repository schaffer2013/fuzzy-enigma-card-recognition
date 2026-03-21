import numpy

from card_engine.art_match import rerank_candidates_by_art
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
