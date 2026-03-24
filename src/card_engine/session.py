from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .api import recognize_card
from .catalog.local_index import CatalogRecord, LocalCatalogIndex
from .catalog.maintenance import ensure_catalog_ready
from .config import EngineConfig, load_engine_config
from .models import Candidate, RecognitionResult
from .operational_modes import CandidatePool, ExpectedCard, normalize_recognition_mode

DEFAULT_TRACK_CONFIDENCE_THRESHOLD = 0.85


@dataclass(frozen=True)
class TrackedPoolEntry:
    name: str
    set_code: str | None
    collector_number: str | None


class TrackedPool:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str | None, str | None], CatalogRecord] = {}

    def add_record(self, record: CatalogRecord) -> None:
        key = (record.name, record.set_code, record.collector_number)
        self._records[key] = record

    def add_records(self, records: list[CatalogRecord]) -> None:
        for record in records:
            self.add_record(record)

    def clear(self) -> None:
        self._records.clear()

    def __len__(self) -> int:
        return len(self._records)

    def entries(self) -> list[TrackedPoolEntry]:
        return [
            TrackedPoolEntry(
                name=record.name,
                set_code=record.set_code,
                collector_number=record.collector_number,
            )
            for record in self._records.values()
        ]

    def snapshot(self) -> CandidatePool:
        return CandidatePool.from_records(list(self._records.values()))


class RecognitionSession:
    def __init__(
        self,
        *,
        config: EngineConfig | None = None,
        catalog: LocalCatalogIndex | None = None,
        auto_track_results: bool = False,
        track_confidence_threshold: float = DEFAULT_TRACK_CONFIDENCE_THRESHOLD,
    ) -> None:
        self.config = config or load_engine_config()
        self._catalog = catalog
        self._tracked_pool = TrackedPool()
        self.auto_track_results = auto_track_results
        self.track_confidence_threshold = track_confidence_threshold

    def recognize(
        self,
        image: Any,
        *,
        mode: str | None = None,
        expected_card: ExpectedCard | None = None,
        candidate_pool: CandidatePool | None = None,
        use_tracked_pool: bool | None = None,
        track_result: bool | None = None,
        progress_callback=None,
        deadline: float | None = None,
    ) -> RecognitionResult:
        resolved_mode = normalize_recognition_mode(mode)
        resolved_pool = candidate_pool
        if resolved_pool is None and self._should_use_tracked_pool(resolved_mode, use_tracked_pool):
            if len(self._tracked_pool) == 0:
                raise ValueError("No tracked pool is available for constrained recognition.")
            resolved_pool = self._tracked_pool.snapshot()

        result = recognize_card(
            image,
            mode=resolved_mode,
            expected_card=expected_card,
            candidate_pool=resolved_pool,
            progress_callback=progress_callback,
            deadline=deadline,
            config=self.config,
            catalog=self._load_catalog(),
        )

        if self._should_track_result(resolved_mode, track_result):
            self.track_recognition_result(result)

        return result

    def track_recognition_result(self, result: RecognitionResult) -> bool:
        if result.confidence < self.track_confidence_threshold:
            return False
        candidate = result.top_k_candidates[0] if result.top_k_candidates else None
        if candidate is None:
            return False
        record = self._resolve_record_from_candidate(candidate)
        if record is None:
            return False
        self._tracked_pool.add_record(record)
        return True

    def add_expected_card(self, expected_card: ExpectedCard) -> bool:
        record = self._load_catalog().find_record(
            name=expected_card.name,
            set_code=expected_card.set_code,
            collector_number=expected_card.collector_number,
        )
        if record is None:
            return False
        self._tracked_pool.add_record(record)
        return True

    def get_tracked_pool(self) -> CandidatePool:
        return self._tracked_pool.snapshot()

    def get_tracked_pool_entries(self) -> list[TrackedPoolEntry]:
        return self._tracked_pool.entries()

    def clear_tracked_pool(self) -> None:
        self._tracked_pool.clear()

    def _load_catalog(self) -> LocalCatalogIndex:
        if self._catalog is None:
            ensure_catalog_ready(db_path=self.config.catalog_path)
            self._catalog = LocalCatalogIndex.from_sqlite(self.config.catalog_path)
        return self._catalog

    def _resolve_record_from_candidate(self, candidate: Candidate) -> CatalogRecord | None:
        return self._load_catalog().find_record(
            name=candidate.name,
            set_code=candidate.set_code,
            collector_number=candidate.collector_number,
        )

    def _should_use_tracked_pool(self, mode: str, use_tracked_pool: bool | None) -> bool:
        if use_tracked_pool is not None:
            return use_tracked_pool
        return mode == "small_pool"

    def _should_track_result(self, mode: str, track_result: bool | None) -> bool:
        if track_result is not None:
            return track_result
        return self.auto_track_results and mode in {"greenfield", "reevaluation"}
