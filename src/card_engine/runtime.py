from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .catalog.local_index import LocalCatalogIndex
from .config import EngineConfig, load_engine_config
from .ocr import _get_paddle_ocr_instance, _get_rapidocr_instance
from .session import RecognitionSession


@dataclass(frozen=True)
class RuntimeWarmupResult:
    catalog_records: int
    rapidocr_ready: bool
    paddleocr_ready: bool


def warm_recognition_runtime(
    *,
    config: EngineConfig | None = None,
    session: RecognitionSession | None = None,
    include_paddle_fallback: bool = False,
) -> RuntimeWarmupResult:
    """Preload expensive steady-state runtime components for live use.

    A warm runtime mirrors the intended embedding pattern: keep one process
    alive, load the catalog once, and initialize OCR engines before the first
    operator-visible recognition request.
    """

    active_config = config or getattr(session, "config", None) or load_engine_config()
    active_session = session or RecognitionSession(config=active_config)
    catalog: LocalCatalogIndex = active_session._load_catalog()

    rapidocr_ready = False
    paddleocr_ready = False
    try:
        _get_rapidocr_instance()
        rapidocr_ready = True
    except Exception:
        rapidocr_ready = False

    if include_paddle_fallback:
        try:
            _get_paddle_ocr_instance()
            paddleocr_ready = True
        except Exception:
            paddleocr_ready = False

    return RuntimeWarmupResult(
        catalog_records=len(catalog.records),
        rapidocr_ready=rapidocr_ready,
        paddleocr_ready=paddleocr_ready,
    )


def build_warmed_session(
    *,
    config: EngineConfig | None = None,
    auto_track_results: bool = False,
    include_paddle_fallback: bool = False,
) -> tuple[RecognitionSession, RuntimeWarmupResult]:
    session = RecognitionSession(config=config, auto_track_results=auto_track_results)
    warmup = warm_recognition_runtime(
        session=session,
        include_paddle_fallback=include_paddle_fallback,
    )
    return session, warmup
