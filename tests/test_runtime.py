from card_engine.catalog.local_index import CatalogRecord, LocalCatalogIndex
from card_engine.runtime import build_warmed_session, warm_recognition_runtime
from card_engine.session import RecognitionSession


def test_warm_recognition_runtime_preloads_catalog_and_rapidocr(monkeypatch):
    catalog = LocalCatalogIndex.from_records([CatalogRecord(name="Opt", normalized_name="")])
    session = RecognitionSession(catalog=catalog)
    seen = {"rapid": 0}

    monkeypatch.setattr("card_engine.runtime._get_rapidocr_instance", lambda: seen.__setitem__("rapid", 1))

    result = warm_recognition_runtime(session=session)

    assert result.catalog_records == 1
    assert result.rapidocr_ready is True
    assert result.paddleocr_ready is False
    assert seen["rapid"] == 1


def test_build_warmed_session_returns_session_and_warmup(monkeypatch):
    monkeypatch.setattr("card_engine.runtime.warm_recognition_runtime", lambda **kwargs: "warm")

    session, warmup = build_warmed_session()

    assert isinstance(session, RecognitionSession)
    assert warmup == "warm"
