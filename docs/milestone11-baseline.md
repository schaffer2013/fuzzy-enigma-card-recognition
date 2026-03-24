# Milestone 11 Baseline

Milestone 11 starts with an explicit operational baseline for the current
paper-only offline recognizer. The goal of this note is to turn the benchmark
workflow into concrete targets, identify the real hotspots, and define the
first optimization backlog from measured data.

## Benchmark Snapshot

Validation was rerun on March 24, 2026 using the existing Milestone 9 closeout
fixture set and the current mode-aware API.

Command:

```powershell
python scripts/eval_fixture_set.py `
  --fixtures-dir data/sample_outputs/random_eval_cards_m9_closeout `
  --operational-modes all `
  --pair-db data/cache/simulated_card_pairs_m11_baseline.sqlite3 `
  --json-out data/sample_outputs/m11-operational-baseline.json
```

The fixture set contains 66 unseen paper-English cards. Long-run ETA reporting
was enabled during the benchmark and completed successfully.

## Baseline Metrics

- `greenfield`: top-1 `1.000`, set `0.970`, art `0.955`, avg runtime `3.824s`, ECE `0.015`
- `reevaluation`: top-1 `1.000`, set `0.970`, art `0.955`, avg runtime `3.382s`, ECE `0.015`
- `small_pool`: top-1 `1.000`, set `0.970`, art `0.955`, avg runtime `1.181s`, ECE `0.066`
- `confirmation`: top-1 `1.000`, set `0.970`, art `0.955`, avg runtime `1.216s`, ECE `0.083`

Approximate throughput implied by the current averages:

- `greenfield`: about `15.7` recognition passes per minute
- `reevaluation`: about `17.7` recognition passes per minute
- `small_pool`: about `50.8` recognition passes per minute
- `confirmation`: about `49.3` recognition passes per minute

Interpretation:

- Open-ended recognition is already accurate enough to serve as a stable
  baseline for performance work.
- Constrained modes are materially faster than open-ended modes, which confirms
  that the mode-aware API and tracked-pool/session work are paying off.
- Calibration remains acceptable in all modes, but `small_pool` and
  `confirmation` now trade some calibration quality for speed. That is
  acceptable at the start of Milestone 11 because the milestone is about
  measured performance engineering, not reworking mode semantics again.

## Stage Hotspots

Measured average stage timings show a very clear picture.

### Open-ended modes

`greenfield` average stage timings:

- `secondary_ocr`: `3.514s`
- `title_ocr`: `1.160s`
- `match_candidates_secondary`: `0.655s`
- `match_candidates_primary`: `0.551s`
- `set_symbol_compare`: `0.025s`
- `art_match_compare`: `0.014s`

`reevaluation` average stage timings:

- `secondary_ocr`: `3.029s`
- `title_ocr`: `0.979s`
- `match_candidates_secondary`: `0.654s`
- `match_candidates_primary`: `0.572s`
- `set_symbol_compare`: `0.020s`
- `art_match_compare`: `0.015s`

Interpretation:

- `secondary_ocr` is still the dominant open-ended bottleneck.
- Candidate matching is meaningful, but it is secondary to OCR cost.
- Visual tie-break stages are cheap relative to OCR and should not be the first
  optimization target.
- Detection, image preparation, and normalization are effectively negligible in
  the current benchmark compared with OCR.

### Constrained modes

`small_pool` average stage timings:

- `title_ocr`: `1.158s`
- `normalize_card`: `0.015s`
- `art_match_compare`: `0.004s`
- `set_symbol_compare`: `0.004s`

`confirmation` average stage timings:

- `title_ocr`: `1.188s`
- `normalize_card`: `0.018s`
- `set_symbol_compare`: `0.007s`
- `art_match_compare`: `0.004s`

Interpretation:

- In constrained modes, runtime is almost entirely `title_ocr`.
- Candidate search and visual tie-break work are already cheap enough that
  they should not be optimized before OCR.
- If constrained-mode latency is going to drop meaningfully from here, the next
  wins will come from OCR policy changes, OCR backend tuning, or OCR caching.

## Milestone 11 Targets

These targets are intended as the next stable bar for the current architecture.

- `greenfield`: sustain `<= 3.5s` average runtime on representative paper-only
  fixture sets without harming name accuracy.
- `reevaluation`: sustain `<= 3.0s` average runtime while preserving the same
  agreement/disagreement semantics already shipped in Milestone 10.
- `small_pool`: sustain `<= 1.0s` average runtime on representative paper-only
  fixture sets.
- `confirmation`: sustain `<= 1.0s` average runtime on representative
  paper-only fixture sets.

These are intentionally modest targets. They are chosen to be achievable with
OCR-focused optimization before considering larger architectural changes.

## Prioritized Optimization Backlog

1. Reduce `secondary_ocr` frequency in open-ended modes through better early
   exits and stronger confidence gating.
2. Reduce `secondary_ocr` cost when it does run by tightening the ROI set and
   avoiding redundant OCR passes.
3. Reduce `title_ocr` cost in constrained modes through OCR backend tuning or
   lightweight caching where the workflow permits it.
4. Recheck candidate-matching cost after OCR changes; do not optimize matching
   first because it is not the dominant bottleneck today.
5. Investigate multithreading only after OCR policy changes are measured, so
   concurrency work is not masking cheaper wins.
6. Defer GPU-path investigation until CPU OCR policy and caching work have been
   measured, because the current benchmark does not justify jumping there first.

## Immediate Next Step

The next Milestone 11 branch should target OCR policy rather than catalog or
visual fingerprint changes:

- reduce unnecessary `secondary_ocr` in open-ended modes
- measure the effect on `greenfield` and `reevaluation`
- then revisit `title_ocr` optimization for `small_pool` and `confirmation`

This keeps the performance work aligned with the current measured hotspots.

## First Optimization Pass

The first optimization pass after establishing this baseline targeted
`secondary_ocr` policy in open-ended modes.

Change:

- skip `secondary_ocr` when the primary pass already yields a single clean
  exact-printing candidate
- skip `secondary_ocr` when the primary pass yields a decisive exact title
  winner against a different-name runner-up
- keep `secondary_ocr` enabled for same-name printing ties, where exact
  printing still needs more evidence

Validation rerun:

```powershell
python scripts/eval_fixture_set.py `
  --fixtures-dir data/sample_outputs/random_eval_cards_m9_closeout `
  --operational-modes all `
  --pair-db data/cache/simulated_card_pairs_m11_optimized.sqlite3 `
  --json-out data/sample_outputs/m11-operational-optimized.json
```

Results on the same 66-card fixture set:

- `greenfield`: `3.824s` -> `2.678s` average runtime, with top-1 still `1.000`
- `reevaluation`: `3.382s` -> `2.423s` average runtime, with top-1 still `1.000`
- `small_pool`: `1.181s` -> `1.227s` average runtime, effectively unchanged
- `confirmation`: `1.216s` -> `1.233s` average runtime, effectively unchanged

Secondary OCR invocation count:

- `greenfield`: `32` fixtures -> `10` fixtures
- `reevaluation`: `32` fixtures -> `10` fixtures

Interpretation:

- The first measured optimization pass achieved a meaningful speedup in the
  modes that were actually dominated by `secondary_ocr`.
- Accuracy stayed flat on the benchmark set, which is the most important guard
  rail for continuing OCR-policy optimization.
- Constrained-mode runtime did not move meaningfully, which reinforces the
  current hypothesis that `title_ocr` is the next constrained-mode target.
