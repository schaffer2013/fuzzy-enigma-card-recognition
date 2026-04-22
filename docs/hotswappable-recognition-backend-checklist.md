# Hotswappable Recognition Backend Checklist

Goal: keep the parent-facing `recognize_card(...)` interface unchanged while allowing the engine backend to switch between our native pipeline and Moss Machine at runtime.

## Completed

- [x] Keep `card_engine.api.recognize_card(...)` as the single public entry point
- [x] Add runtime backend selection through `EngineConfig.recognition_backend`
- [x] Add safe fallback through `EngineConfig.recognition_backend_fallback`
- [x] Normalize Moss output into the existing `RecognitionResult` contract
- [x] Preserve caller compatibility for the parent repo by swapping under the API boundary instead of above it
- [x] Auto-stage cached Moss database assets from `data/cache/moss-machine/`
- [x] Prefer hard-link staging for Moss DB assets and fall back to copy when links are unavailable
- [x] Add targeted tests for Moss routing and fallback behavior

## Backend Selection

- [x] Default backend remains `fuzzy_enigma`
- [x] Support `moss_machine` as a selectable backend
- [x] Honor `CARD_ENGINE_BACKEND` as an override for local experiments
- [ ] Add a UI control in the debug app to switch the active backend without editing config files
- [ ] Add a CLI flag for evaluation and manual comparison scripts to force backend selection directly

## Parent Contract Safety

- [x] Return `RecognitionResult` from both backends
- [x] Preserve `best_name`, `confidence`, `top_k_candidates`, `failure_code`, `review_reason`, and `debug`
- [x] Record `debug.backend.requested`, `debug.backend.effective`, and fallback reasons
- [ ] Standardize Moss candidate casing and collector-number normalization to match the native engine more closely
- [ ] Decide whether Moss should synthesize `bbox` when a fixture sidecar contains saved detection metadata

## Fallback Rules

- [x] Fall back to `fuzzy_enigma` when Moss cannot support the request safely
- [x] Fall back when the input is not a real on-disk image path
- [x] Fall back when the request depends on `candidate_pool`, `expected_card`, `visual_pool_candidates`, explicit catalog injection, or unsupported modes
- [ ] Add an explicit "force Moss only" path for benchmarking where fallback should be treated as a hard failure

## Moss Coverage Gaps

- [ ] Add a Moss-compatible implementation for `small_pool`
- [ ] Add a Moss-compatible implementation for `reevaluation`
- [ ] Add a Moss-compatible implementation for `confirmation`
- [ ] Decide how tracked-pool and expected-card semantics should map onto Moss, or explicitly scope them out
- [ ] Improve split / transform / multi-face normalization when Moss returns only the front face

## Operational Hardening

- [ ] Surface backend choice in the UI status panel and exported artifact manifests
- [ ] Add backend selection to benchmark and evaluation outputs so reports are self-describing
- [ ] Add smoke tests that run the real Moss subprocess when assets are present locally
- [ ] Cache and reuse Moss runtime setup across repeated runs where safe
- [x] Measure and switch `phash_cards_*.db` staging from copy-first to hard-link-first

## Rollout Sequence

1. Keep the default backend on `fuzzy_enigma`.
2. Use config or `CARD_ENGINE_BACKEND=moss_machine` for controlled experiments.
3. Expand script and UI controls so switching does not require code edits.
4. Close the mode-support gaps or explicitly document which modes always fall back.
5. Add real-backend smoke tests and evaluation reporting before exposing backend switching more broadly.
