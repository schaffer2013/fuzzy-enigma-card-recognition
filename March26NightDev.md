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
## 2026-03-27 07:47 PDT
- Added a narrower split-room latency gate on `feature/split-room-latency`.
- New behavior: skip `split_full` rescue when the first split-title OCR already covers the same split-card name family strongly enough from catalog-backed evidence, but keep the rescue path for cards that still need recovery.
- Validation:
  - full suite: `184 passed`
  - constrained room benchmark rerun (`59` fixtures) still holds `1.000` top-1 for both `small_pool` and `confirmation`
- Measured constrained-mode improvement on the room family:
  - `small_pool`: `15.722s -> 9.921s`
  - `confirmation`: `14.744s -> 8.749s`
- Runtime note:
  - that constrained rerun still took about `18.5 minutes`, so this branch is improving latency but not yet "fast enough" for all split-room cases
## 2026-03-27 08:12 PDT
- Started a new feature branch: `feature/recognition-deadlines`.
- Added `recognition_deadline_seconds` to `EngineConfig` and the sample config, with `20.0` seconds as the default runtime budget.
- Recognition now marks over-budget scans as failures instead of slow successes, and evaluation classifies them as `runtime_budget_exceeded`.
- Updated README, INTEGRATION, HOWTO, mode-pipeline docs, and the speed-tuning deep dive so the runtime-budget policy is explicit.
- Validation:
  - focused suites: `69 passed`
  - full suite: `186 passed`
## 2026-03-27 08:59 PDT
- Reran the full `room` family benchmark (`59` fixtures) with the new 20-second recognition budget active.
- Result:
  - `greenfield`: `0.966` top-1, `15.527s` average, `2` runtime-budget failures
  - `reevaluation`: `1.000` top-1, `13.904s` average
  - `small_pool`: `1.000` top-1, `8.968s` average
  - `confirmation`: `1.000` top-1, `9.041s` average
- The deadline budget therefore cleaned up the worst room-family tails without harming constrained modes.
- The remaining room-family greenfield budget failures are:
  - `central-elevator-promising-stairs-pdsk-44s`
  - `derelict-attic-widow-s-walk-dsk-93`
- Runtime note:
  - this all-modes room rerun still took about `47 minutes`, so it is much better than the old ~76-minute run, but it is still a heavy benchmark and should be used selectively.
## 2026-03-27 09:33 PDT
- Started a new branch: `feature/split-room-greenfield-budget`.
- Removed the unnecessary `0`-degree OCR attempt for vertical title regions (`planar_title` and `split_full` now try only `90` and `270`).
- Added an early-stop rule for split/planar title OCR so a strong `planar_title` read can skip the extra `standard` title pass.
- Result on the full `room` family benchmark (`59` fixtures):
  - `greenfield`: `1.000` top-1, `8.268s` average, `15.266s` max
  - `reevaluation`: `1.000` top-1, `7.302s` average
  - `small_pool`: `1.000` top-1, `4.569s` average
  - `confirmation`: `1.000` top-1, `4.491s` average
- This is the first room-family run that is both fully correct and comfortably under the 20-second runtime budget in all four modes.
## 2026-03-27 10:05 PDT
- Started a new branch: `feature/benchmark-runtime-budget`.
- Replayed the unmerged room-latency, recognition-deadline, and room-budget improvements on top of the actual `main` head before continuing.
- Fixed the benchmark/runtime-budget policy so evaluation runs no longer use the same strict per-card ceiling as live recognition.
- New benchmark policy:
  - live recognition still defaults to `20.0s` per card
  - evaluation defaults to `20x` that budget, so the default benchmark ceiling is `400.0s` per card
- Updated README, INTEGRATION, HOWTO, mode-pipeline docs, and the speed-tuning note so that policy is explicit.
- Validation:
  - `pytest tests/test_evaluation.py -q` -> `32 passed`
  - full suite -> `189 passed`
- Next focus:
  1. benchmark the `classic_split` family on the current branch with the corrected benchmark budget
  2. use that result to choose the next split-family latency/correctness target
