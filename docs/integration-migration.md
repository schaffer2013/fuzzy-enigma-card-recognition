# Integration Migration: Debug Parsing -> Structured Result Fields

This note describes how parent integrations should migrate from debug-payload scraping to stable top-level recognition fields.

## Why migrate

Previously, integrations often inferred behavior from `result.debug["mode"]` and string-matched errors.

Now, use first-class fields:

- `result.requested_mode`
- `result.effective_mode`
- `result.mode_flags`
- `result.failure_code`
- `result.review_reason`

These fields are stable machine-readable contracts intended for routing, metrics, and recovery flows.

## Recommended migration pattern

### Before

- Parse `result.debug["mode"]["requested"]`
- Parse `result.debug["mode"]["effective"]`
- Catch exceptions for constrained-mode preconditions
- Infer review reasons from mixed debug strings and local policy

### After

- Read `result.requested_mode` and `result.effective_mode` directly
- Use `result.mode_flags` for pool/expected-card/tracked-pool context
- Route by `result.failure_code` / `result.review_reason`
- Treat unknown codes as `review_required` and retain debug payload for diagnostics

## Example decision routing

- `missing_tracked_pool`: request operator/session setup and continue benchmark safely
- `expected_card_contradicted`: surface confirmation disagreement workflow
- `deadline_exceeded`: retry with larger timeout or queue for manual review
- `candidate_tie_unresolved`: trigger disambiguation step (set/collector refinement)

## Artifact export adoption

If you need portable evidence bundles, pass `artifact_export_dir` to `recognize_card(...)` or session/adapter entry points that forward it.

Expected outputs include:

- `recognition_artifacts.json`
- `normalized.png` (when available)
- `crops/*.png` (when available)

This reduces parent-side reconstruction work and keeps evidence packaging engine-authored.
