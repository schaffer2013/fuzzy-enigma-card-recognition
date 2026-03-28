# Parent-Facing Controls and Data Contracts

This document defines stable parent-facing controls for operational-mode recognition, offline catalog querying, and optional artifact export.

## Recognition controls

## Expected card inputs

`recognize_card(...)`, `RecognitionSession.recognize(...)`, and `SortingMachineRecognizer.recognize_top_card(...)` support passing `expected_card` with:

- `name` (required for expected-card semantics)
- `set_code` (optional printing refinement)
- `collector_number` (optional printing refinement)

Mode expectations:

- `reevaluation`: requires `expected_card`; disagreements remain possible
- `confirmation`: requires `expected_card`; contradiction is surfaced via `expected_card_contradicted`
- `small_pool`: can use `expected_card` to constrain same-name printings when no explicit candidate pool is provided

## Candidate-pool inputs

`candidate_pool` is accepted on session and adapter entry points and forwarded into the recognizer pipeline.

- If supplied, `candidate_pool` is the constrained search set
- If not supplied and `small_pool` is active, tracked pool may be used (unless `use_tracked_pool=False`)
- If tracked-pool usage is requested but unavailable, result returns structured `missing_tracked_pool`

Mode flags expose these decisions via:

- `mode_flags.has_candidate_pool`
- `mode_flags.used_tracked_pool`
- `mode_flags.used_visual_small_pool`

## Offline catalog query API

Use `OfflineCatalogQuery` as the stable Python surface:

- `find_oracle_cards(name_query, limit=...)`
- `get_oracle_card(oracle_id)`
- `get_printed_card(scryfall_id)`
- `find_printed_cards(name_query=..., oracle_id=..., set_code=..., collector_number=..., limit=...)`
- `find_printing_candidates(name_query=..., set_code=..., collector_number=..., limit=...)`
- `resolve_card_identity(name_query=..., oracle_id=..., scryfall_id=..., set_code=..., collector_number=...)`

CLI script `scripts/query_offline_catalog.py` is a thin wrapper over this API.

## Optional artifact export

`recognize_card(...)` accepts `artifact_export_dir`.

When provided, the engine exports:

- `recognition_artifacts.json` with:
  - bbox
  - OCR lines
  - candidate list
  - timings
  - mode metadata
  - failure/review reason codes
- `normalized.png` (when available)
- `crops/*.png` ROI crops (when available)

This enables parent repos to inspect consistent evidence bundles directly from engine output.
