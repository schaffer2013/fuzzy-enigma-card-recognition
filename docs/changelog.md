# Changelog

## Unreleased

### Added

- Stable machine-readable recognition result fields:
  - `requested_mode`
  - `effective_mode`
  - `mode_flags`
  - `failure_code`
  - `review_reason`
- Structured precondition and runtime failure codes in normal recognition/session flows, including:
  - `missing_tracked_pool`
  - `missing_expected_card`
  - `missing_candidate_pool_or_expected_card`
  - `expected_card_not_found`
  - `detection_failed`
  - `ocr_weak`
  - `candidate_tie_unresolved`
  - `expected_card_contradicted`
  - `deadline_exceeded`
- Optional engine-side artifact export via `artifact_export_dir` with `recognition_artifacts.json` and image artifacts when available.
- Offline catalog API helpers:
  - `OfflineCatalogQuery.resolve_card_identity(...)`
  - `OfflineCatalogQuery.find_printing_candidates(...)`
- CLI additions in `scripts/query_offline_catalog.py`:
  - `card-identity`
  - `printing-candidates`

### Changed

- Constrained-mode precondition failures and detector errors now return structured `RecognitionResult` payloads instead of raising in common parent-facing paths.
- Evaluation runtime output now includes candidate-pool context as `tested against {X} candidates`.
