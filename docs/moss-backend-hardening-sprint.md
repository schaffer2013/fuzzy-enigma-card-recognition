# Moss Backend Hardening Sprint

Date started: 2026-04-22

## Goal

Make the optional Moss Machine backend usable as a parent-facing experiment
lane without surprising fallbacks, hidden timing gaps, or missing controls.

## Sprint Items

- [ ] Add explicit UI backend switching.
- [ ] Add evaluation CLI backend selection and forced-backend behavior.
- [ ] Make unsupported forced Moss requests fail loudly instead of scanning with
  ignored semantics.
- [ ] Extend Moss post-processing for `small_pool`, `reevaluation`, and
  `confirmation` semantics.
- [ ] Normalize Moss candidates to match native casing and collector-number
  conventions more closely.
- [ ] Preserve fixture sidecar bbox data in Moss results when available.
- [ ] Surface backend choice in UI summaries, artifact manifests, and evaluation
  JSON/report output.
- [ ] Add real Moss smoke coverage that skips cleanly when local assets are not
  present.
- [ ] Add an explicit runtime-asset reuse option for repeated Moss runs.
- [ ] Update docs and checklist when the sprint is complete.

## Completion Criteria

- Focused backend, evaluation, and UI tests pass.
- Engine-only test suite passes.
- Moss smoke tests either pass locally when assets exist or skip with a clear
  reason.
- Changes are committed in logical chunks and pushed after the final green run.
