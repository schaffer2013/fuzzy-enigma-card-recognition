from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
import json
import os
import random
import time
from typing import Callable

from .art_match import (
    ART_MATCH_CACHE_DIR,
    _cached_fingerprint,
    _load_or_compute_reference_fingerprint,
    _reference_cache_name,
    _refresh_reference_cache_if_needed,
)
from .catalog.local_index import CatalogRecord, LocalCatalogIndex


DEFAULT_ART_PREHASH_WORKERS = min(6, max(1, os.cpu_count() or 1))


@dataclass(frozen=True)
class ArtPrehashProgress:
    completed: int
    total: int
    successes: int
    failures: int
    current_label: str
    elapsed_seconds: float
    eta_seconds: float

    @property
    def cards_per_second(self) -> float:
        if self.elapsed_seconds <= 0:
            return 0.0
        return self.completed / self.elapsed_seconds

    @property
    def message(self) -> str:
        return (
            f"[{self.completed}/{self.total}] {self.successes} hashed, {self.failures} failed | "
            f"current: {self.current_label} | elapsed: {self.elapsed_seconds:.1f}s | "
            f"rate: {self.cards_per_second:.2f} cards/s | eta: {self.eta_seconds:.1f}s"
        )


@dataclass(frozen=True)
class ArtPrehashResult:
    total_eligible: int
    already_hashed: int
    attempted: int
    newly_hashed: int
    failures: list[str]
    elapsed_seconds: float
    cancelled: bool = False


def load_eligible_art_records(catalog_path: str | Path) -> list[CatalogRecord]:
    catalog = LocalCatalogIndex.from_sqlite(str(catalog_path))
    return eligible_art_records(catalog.records)


def eligible_art_records(records: list[CatalogRecord]) -> list[CatalogRecord]:
    eligible: list[CatalogRecord] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for record in records:
        if not record.image_uri:
            continue
        if record.games and "paper" not in {game.lower() for game in record.games}:
            continue
        key = (record.scryfall_id, record.set_code, record.collector_number)
        if key in seen:
            continue
        seen.add(key)
        eligible.append(record)
    return eligible


def count_valid_cached_art_records(
    records: list[CatalogRecord],
    *,
    cache_dir: str | Path = ART_MATCH_CACHE_DIR,
) -> int:
    cache_root = Path(cache_dir)
    return sum(1 for record in records if _has_valid_cached_fingerprint(record, cache_dir=cache_root))


def prehash_missing_art_records(
    records: list[CatalogRecord],
    *,
    cache_dir: str | Path = ART_MATCH_CACHE_DIR,
    limit: int = 0,
    shuffle: bool = False,
    download_timeout_seconds: float = 10.0,
    progress_callback: Callable[[ArtPrehashProgress], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    max_workers: int = DEFAULT_ART_PREHASH_WORKERS,
) -> ArtPrehashResult:
    cache_root = Path(cache_dir)
    _refresh_reference_cache_if_needed()
    ordered = list(records)
    missing = [record for record in ordered if not _has_valid_cached_fingerprint(record, cache_dir=cache_root)]
    if shuffle:
        random.shuffle(missing)
    else:
        missing.sort(key=_record_secondary_sort_key)
        missing.sort(key=lambda record: record.released_at or "", reverse=True)
    if limit > 0:
        missing = missing[:limit]

    total_eligible = len(ordered)
    already_hashed = total_eligible - len(missing)
    if not missing:
        return ArtPrehashResult(
            total_eligible=total_eligible,
            already_hashed=already_hashed,
            attempted=0,
            newly_hashed=0,
            failures=[],
            elapsed_seconds=0.0,
            cancelled=False,
        )

    cache_root.mkdir(parents=True, exist_ok=True)
    started_at = time.monotonic()
    successes = 0
    failures: list[str] = []
    cancelled = False
    completed = 0
    worker_count = max(1, max_workers)

    def do_prehash(record: CatalogRecord) -> tuple[str, bool]:
        fingerprint = _load_or_compute_reference_fingerprint(
            record,
            download_timeout_seconds=download_timeout_seconds,
        )
        return record_label(record), fingerprint is not None

    pending_records = iter(missing)
    in_flight: dict[Future, CatalogRecord] = {}

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="art-prehash") as executor:
        accepting_new_work = True
        while len(in_flight) < worker_count:
            try:
                record = next(pending_records)
            except StopIteration:
                break
            in_flight[executor.submit(do_prehash, record)] = record

        while in_flight:
            if should_stop is not None and should_stop():
                cancelled = True
                accepting_new_work = False

            done, _ = wait(in_flight.keys(), return_when=FIRST_COMPLETED)
            for future in done:
                record = in_flight.pop(future)
                if future.cancelled():
                    continue

                label, succeeded = future.result()
                completed += 1
                if succeeded:
                    successes += 1
                else:
                    failures.append(label)

                if progress_callback is not None:
                    elapsed = max(0.001, time.monotonic() - started_at)
                    rate = completed / elapsed
                    remaining = max(0, len(missing) - completed)
                    eta_seconds = remaining / rate if rate > 0 else 0.0
                    progress_callback(
                        ArtPrehashProgress(
                            completed=completed,
                            total=len(missing),
                            successes=successes,
                            failures=len(failures),
                            current_label=label,
                            elapsed_seconds=elapsed,
                            eta_seconds=eta_seconds,
                        )
                    )

                if accepting_new_work:
                    if should_stop is not None and should_stop():
                        cancelled = True
                        accepting_new_work = False
                        continue
                    try:
                        next_record = next(pending_records)
                    except StopIteration:
                        continue
                    in_flight[executor.submit(do_prehash, next_record)] = next_record

    return ArtPrehashResult(
        total_eligible=total_eligible,
        already_hashed=already_hashed,
        attempted=(successes + len(failures)),
        newly_hashed=successes,
        failures=failures,
        elapsed_seconds=round(time.monotonic() - started_at, 4),
        cancelled=cancelled,
    )


def record_label(record: CatalogRecord) -> str:
    return f"{record.name} [{record.set_code or '?'} {record.collector_number or '?'}]"


def _has_valid_cached_fingerprint(record: CatalogRecord, *, cache_dir: Path) -> bool:
    cache_path = cache_dir / _reference_cache_name(record)
    if not cache_path.exists():
        return False
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return _cached_fingerprint(payload) is not None


def _record_secondary_sort_key(record: CatalogRecord) -> tuple[str, str, str]:
    return (
        record.name.lower(),
        (record.set_code or "").lower(),
        str(record.collector_number or "").lower(),
    )
