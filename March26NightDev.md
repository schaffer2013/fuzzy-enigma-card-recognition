# March 26 Night Dev Log

## 2026-03-26 22:15 PDT
- Confirmed working branch: `feature/split-fallback-rois`.
- Committed split-family reporting and evaluation typing fixes.
- Full split benchmark rerun on current branch is still too long/stall-prone to use as a tight inner-loop check.
- Next focus:
  1. Milestone 12 offline query layer.
  2. Milestone 13 UI/engine decoupling.
  3. Return to split-family handling with better-targeted validation.
## 2026-03-26 22:35 PDT
- Added offline query layer (`OfflineCatalogQuery`) and `query_offline_catalog.py`.
- Added engine-only/UI-only test collection switches in `tests/conftest.py`.
- Moved `EditableLoadedImage` out of the UI module so core tests no longer import `card_engine.ui.app`.
- Validation complete so far:
  - `pytest --engine-only`
  - `pytest --ui-only`
  - full `pytest`
  - direct query script smoke test
- Next: commit the M12/M13 slice, then return to split-family recognition work.
## 2026-03-26 23:25 PDT
- Added split-family fixture filtering so targeted family benchmarks are easy to build.
- Ran the full current-code operational benchmark on the `aftermath` family (70 fixtures).
- Result: `1.000` top-1 across all four operational modes.
- Conclusion: the catastrophic old aftermath result was stale; current split/title handling has fixed that family.
- Next target: benchmark the `room` family, which is now the most likely remaining split-family problem.
## 2026-03-27 00:10 PDT
- Added room-friendly split_full title reconstruction in the matcher.
- Added a split_full recovery path in the API that reopens catalog search instead of reranking only the already-wrong first-pass candidates.
- Direct spot checks now recover previously failing room cards:
  - Meat Locker // Drowned Diner
  - Mirror Room // Fractured Realm
  - Restricted Office // Lecture Hall
  - Unholy Annex // Ritual Chamber
- Next: rerun the room-family benchmark to quantify the improvement.
## 2026-03-27 01:35 PDT
- Added split-family fixture filtering so family-specific validation is easy to rerun.
- Validated the `aftermath` family separately and confirmed it is no longer a current problem: `1.000` top-1 across all four operational modes.
- Added split_full title reconstruction that combines plausible room-title fragments into a single exact-lookup query before reopening recovery.
- Added a split-specific recovery pool for rotated whole-card OCR so split fallback does not have to reopen the full catalog.
- Added a constrained-mode exception so `small_pool` and `confirmation` can still use split_full recovery even when they would normally skip secondary OCR.
## 2026-03-27 06:31 PDT
- Reran the full `room` family benchmark cleanly on current code (`59` fixtures).
- Result: `1.000` top-1 across `greenfield`, `reevaluation`, `small_pool`, and `confirmation`.
- Important runtime note: this benchmark still takes a long time.
  - `greenfield` average runtime: `21.008s`
  - `reevaluation` average runtime: `25.722s`
  - `small_pool` average runtime: `15.722s`
  - `confirmation` average runtime: `14.744s`
- Interpretation:
  - accuracy for room cards is now in good shape
  - runtime for split-room handling is still expensive enough that future split-family work should focus on latency, not just correctness
