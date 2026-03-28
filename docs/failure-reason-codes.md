# Failure and Review Reason Codes

This document defines machine-readable `failure_code` / `review_reason` values emitted by `RecognitionResult`.

## Stability Contract

- Codes below are intended to be consumed by embedding/parent repositories.
- New codes may be added over time, but existing codes should not be renamed without a deprecation period.
- `failure_code` and `review_reason` currently share the same normalized value when a reviewable failure condition is present.

## Code Mapping

| Code | Trigger condition | Source path |
|---|---|---|
| `missing_tracked_pool` | Session requested constrained tracked-pool usage (`small_pool` default behavior) but no tracked pool entries exist. | `RecognitionSession.recognize(...)` |
| `missing_expected_card` | Mode precondition requires an expected card and none was supplied (for example `reevaluation`, `confirmation`). | mode resolution precondition |
| `missing_candidate_pool_or_expected_card` | Constrained mode requested but neither `candidate_pool` nor `expected_card` was available to constrain catalog. | mode resolution precondition |
| `expected_card_not_found` | `expected_card` was supplied for constrained lookup but no matching name exists in catalog. | constrained catalog resolution |
| `detection_failed` | Detector stage raised an exception and recognition returns a structured failure payload. | recognition API detect stage |
| `ocr_weak` | OCR signal is too weak to support a confident result (for example no OCR lines with low confidence and no viable match). | review-reason derivation |
| `candidate_tie_unresolved` | Top two candidates are effectively tied and represent distinct printings / identities within tie threshold. | review-reason derivation |
| `expected_card_contradicted` | In `confirmation` mode, scoring indicates strongest result contradicts expected card. | confirmation scoring + review-reason derivation |
| `deadline_exceeded` | Deadline finalization marks the result as timed out and downgrades output to a reviewable failure. | recognition finalization |

## Notes for Embedding Repos

- Treat unknown codes as `review_required` and retain raw debug payload for diagnostics.
- Prefer code-based routing/metrics over parsing debug strings.
- When reporting operator-facing errors, surface both code and any relevant compact context (mode, expected identifiers, top candidates).
