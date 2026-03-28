# Parent-Facing Controls and Data Contracts

This document defines stable parent-facing controls for operational-mode recognition, offline catalog querying, and optional artifact export.

## Recognition controls

## Expected card inputs

`recognize_card(...)`, `RecognitionSession.recognize(...)`, and `SortingMachineRecognizer.recognize_top_card(...)` support passing `expected_card` with:

- `scryfall_id` (preferred exact-printing identifier)
- `oracle_id` (preferred grouped same-card identifier across printings)
- `name` (optional fallback when parent only has a human-readable card name)
- `set_code` (optional printing refinement)
- `collector_number` (optional printing refinement)

Parent-facing recommendation:

- pass `scryfall_id` when the parent already knows the exact printing
- pass `oracle_id` when the parent wants same-card grouping across printings
- only rely on `name` when identifiers are not yet available

Identifier resolution is now preferred ahead of name matching. When both IDs and
name are provided, the identifier path wins and the name acts as extra context.

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

## Pipeline summary

Recognition results now also expose a concise top-level `pipeline_summary`
alongside `mode_flags` and `debug`.

Stable fields include:

- `resolution_path`
- `active_title_roi`
- `title_rois_with_text`
- `secondary_rois_with_text`
- `used_secondary_ocr`
- `used_set_symbol_compare`
- `used_art_match_compare`
- `used_expected_bias`
- `used_confirmation_scoring`
- `used_visual_small_pool`
- `used_split_full_fallback`
- `branches_fired`

Use `pipeline_summary` for parent-side routing and metrics first, then retain
`debug` as the deeper diagnostic payload.

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
