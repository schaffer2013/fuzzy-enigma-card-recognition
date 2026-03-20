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

    def fake_similarity(record, *, observed_hash, progress_callback=None):
        return 0.96 if record.set_code == "SLD" else 0.51

    monkeypatch.setattr("card_engine.set_symbol._reference_similarity_for_record", fake_similarity)
    monkeypatch.setattr("card_engine.set_symbol._compute_average_hash", lambda *_args, **_kwargs: "f" * 16)

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

