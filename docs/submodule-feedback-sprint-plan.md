# Sprint Plan: Parent Feedback Alignment

This checklist translates parent integration feedback into concrete implementation tasks.

## Sprint Objectives

- [ ] Replace mode/precondition exceptions in normal recognition paths with structured failure results and stable codes.
- [ ] Expose first-class mode metadata on `RecognitionResult` and adapter outputs (without requiring debug parsing).
- [ ] Keep parent-facing expected-card and candidate-pool controls explicit and stable.
- [ ] Add stable machine-readable failure/review reason codes for common failure clusters.
- [ ] Define a structured Python offline-catalog query surface suitable for embedding repos.
- [ ] Design optional engine-side artifact export to reduce duplicate evidence packaging in parent repos.

## Phase 1 (Started): Structured failures + mode metadata

- [x] Add structured result fields for `requested_mode`, `effective_mode`, `mode_flags`, `failure_code`, and `review_reason`.
- [x] Return structured `missing_tracked_pool` from `RecognitionSession.recognize(...)` instead of raising.
- [x] Wire structured mode metadata into adapter detailed output.
- [ ] Expand API-level mode-precondition failures to standardized failure result payloads across all constrained paths.
- [ ] Add/refresh tests for structured metadata and failure-code behavior.

## Phase 2: Failure code normalization

- [ ] Introduce stable codes for representative classes:
  - [ ] `deadline_exceeded`
  - [ ] `detection_failed`
  - [ ] `ocr_weak`
  - [ ] `candidate_tie_unresolved`
  - [ ] `expected_card_contradicted`
- [ ] Document mapping from internal conditions to external failure/review codes.

## Phase 3: Parent-facing control hardening

- [ ] Validate and document expected-card identifier usage in `reevaluation`, `confirmation`, and `small_pool` paths.
- [ ] Validate and document candidate-pool identifier usage across adapter/session/api boundaries.
- [ ] Add deterministic tests for tracked-pool toggles and visual small-pool path signaling.

## Phase 4: Offline catalog API + artifact export

- [ ] Add Python API for offline queries by name, IDs, and print refinement fields.
- [ ] Keep CLI wrappers thin over Python query API.
- [ ] Add optional artifact export bundle schema (normalized image, ROIs, OCR, bbox, candidates, timings, mode metadata).

## Deliverables

- [ ] Changelog entry describing newly stable fields and failure codes.
- [ ] Integration note for parent repos showing migration from debug parsing to structured fields.
