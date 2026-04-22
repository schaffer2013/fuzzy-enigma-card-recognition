# Moss Backend Hardening Sprint

Date started: 2026-04-22

## Goal

Make the optional Moss Machine backend usable as a parent-facing experiment
lane without surprising fallbacks, hidden timing gaps, or missing controls.

## Sprint Items

- [x] Add explicit UI backend switching.
- [x] Add evaluation CLI backend selection and forced-backend behavior.
- [x] Make unsupported forced Moss requests fail loudly instead of scanning with
  ignored semantics.
- [x] Extend Moss post-processing for `small_pool`, `reevaluation`, and
  `confirmation` semantics.
- [x] Normalize Moss candidates to match native casing and collector-number
  conventions more closely.
- [x] Preserve fixture sidecar bbox data in Moss results when available.
- [x] Surface backend choice in UI summaries, artifact manifests, and evaluation
  JSON/report output.
- [x] Add real Moss smoke coverage that skips cleanly when local assets are not
  present.
- [x] Add an explicit runtime-asset reuse option for repeated Moss runs.
- [x] Update docs and checklist when the sprint is complete.

## Completion Criteria

- [x] Focused backend, evaluation, and UI tests pass.
- [x] Engine-only test suite passes.
- [x] Moss smoke tests either pass locally when assets exist or skip with a clear
  reason.
- [x] Changes are committed in logical chunks and pushed after the final green run.

## Validation

- `python -m compileall src scripts tests`
- Focused Moss/evaluation/UI pytest slice: `25 passed`
- Engine-only pytest: `206 passed`
- Full pytest suite: `224 passed`

## User-Facing Controls

- Config: `recognition_backend`, `recognition_backend_fallback`,
  `moss_active_games`, and `moss_keep_staged_assets`.
- API: `recognize_card(..., backend="moss_machine")` for one-call overrides.
- Evaluation CLI: `--backend moss_machine` plus `--force-backend` when fallback
  should be treated as a benchmark failure.
- Debug UI: toolbar backend selector with the active backend shown in fixture
  and status summaries.

## Remaining Scope

Visual-pool candidates and explicit catalog injection still fall back to the
native backend. Split, transform, and multi-face normalization can still be
improved when Moss returns only one face name.
