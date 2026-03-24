# Milestone 9 Closeout

Milestone 9 closes with a name-first success criterion for paper printings.
Exact printing disambiguation remains useful, but it is secondary unless it
harms card-name accuracy.

## Validation Snapshot

Validation was rerun on March 24, 2026 using fresh paper-English random
fixtures and the current repo configuration.

### Random sample evaluation

Command:

```powershell
python scripts/eval_fixture_set.py `
  --random-time-limit-minutes 10 `
  --random-output-dir data/sample_outputs/random_eval_cards_m9_closeout `
  --pair-db data/cache/simulated_card_pairs_m9_closeout.sqlite3 `
  --json-out data/sample_outputs/m9-closeout-random-summary.json
```

Results on 66 unseen paper-English fixtures:

- Top-1 name accuracy: `1.000`
- Top-5 name accuracy: `1.000`
- Set accuracy: `0.955`
- Art/printing accuracy: `0.939`
- Average confidence: `0.979`
- Expected calibration error (ECE): `0.021`
- Average runtime: `7.050s`

Stage-timing hotspots:

- `secondary_ocr`: `5.236s`
- `title_ocr`: `1.424s`
- `match_candidates_primary`: `1.361s`

Interpretation:

- Name recognition on paper printings is currently strong enough to treat the
  recognizer as Milestone 9 complete.
- Confidence calibration is acceptable on this larger unseen sample and did
  not justify a scoring-threshold rebalance in this closeout pass.
- The main remaining performance hotspot is still `secondary_ocr`, not card
  detection or normalization.

### Operational validation

Command:

```powershell
python scripts/eval_fixture_set.py `
  --fixtures-dir data/sample_outputs/random_eval_cards_m9_closeout `
  --operational-modes greenfield,small_pool `
  --pair-db data/cache/simulated_card_pairs_m9_closeout.sqlite3 `
  --json-out data/sample_outputs/m9-closeout-operational.json
```

Results on the same 66-card fixture set:

- `greenfield`: top-1 `1.000`, set `0.970`, art `0.955`, avg runtime `5.077s`, ECE `0.016`
- `small_pool`: top-1 `1.000`, set `0.970`, art `0.955`, avg runtime `1.639s`, ECE `0.066`

Interpretation:

- `small_pool` now shows the intended constrained-mode latency win while
  preserving name accuracy.
- The higher `small_pool` ECE is acceptable for Milestone 9 because
  mode-specific confidence semantics are a Milestone 10 concern.

## Shipped Milestone 9 Outcomes

- Paper-only evaluation and regression export flows.
- Confidence-bin reporting, ECE reporting, and saved-summary comparisons.
- Set-symbol and art-region visual tie-breaks for same-name printings.
- Fast-path skipping of secondary OCR in confident/constrained flows.
- Repo-committed ROI definitions and ROI-based cache invalidation.
- Stage-level timing in recognition and evaluation output.
- A repeatable benchmark workflow with ETA reporting for long runs.

## Explicit Deferrals

These items were intentionally not required to close Milestone 9:

- Split-card and other nonstandard title-placement fallback OCR.
- Deeper exact-printing optimization when name recognition is already correct.
- Full operational-mode confidence semantics, which belong to Milestone 10.
