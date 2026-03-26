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

## Tail-Latency Follow-up

The next performance pass focused on runtime spread rather than averages alone.
That matters because the real deployment target is a Raspberry Pi 5 in a
pile-sorting workflow, where occasional multi-second stalls are worse than a
slightly higher steady baseline.

On the current 20-card benchmark slice, variance-aware reporting showed:

- `greenfield`: average `4.715s`, median `1.992s`, p95 `13.971s`, max `21.437s`
- `reevaluation`: average `3.170s`, median `1.351s`, p95 `10.794s`, max `11.625s`
- `small_pool`: average `1.343s`, median `1.297s`, p95 `1.496s`, max `1.719s`
- `confirmation`: average `1.345s`, median `1.343s`, p95 `1.503s`, max `1.562s`

Interpretation:

- `small_pool` and `confirmation` are already predictable enough for repeated
  constrained scans.
- The open-ended modes are not broadly slow; they are mostly suffering from a
  small number of pathological outliers.
- The bad tail is driven by OCR ambiguity and the fallback path, not by visual
  tie-break work.

## Tail-Tuning Pass

The current tail-tuning pass did two things:

- secondary matching now reranks within the already plausible candidate set
  instead of rescanning the whole catalog
- secondary OCR can stop after the first useful supporting ROI instead of
  always consuming every secondary region

Current 20-card validation after that pass:

- `greenfield`: average `4.279s`, median `2.852s`, p95 `13.462s`, max `13.625s`
- `reevaluation`: average `2.863s`, median `1.516s`, p95 `8.151s`, max `8.359s`
- `small_pool`: average `1.492s`, median `1.469s`, p95 `1.978s`, max `2.156s`
- `confirmation`: average `1.536s`, median `1.523s`, p95 `1.751s`, max `1.766s`

Interpretation:

- The open-ended modes improved where it matters most for a Pi deployment:
  worst-case latency.
- `greenfield` max runtime dropped from `21.437s` to `13.625s`.
- `reevaluation` max runtime dropped from `11.625s` to `8.359s`.
- Constrained modes regressed slightly, but they remain in a much healthier
  latency band than the open-ended modes.

This is a trade that still makes sense for the current deployment target,
because the most disruptive user-facing behavior on Pi is the open-ended stall,
not a few extra tenths of a second in already constrained flows.

## Raspberry Pi 5 Conclusions

Milestone 11 should be interpreted through the expected Raspberry Pi 5 target,
not through desktop-only assumptions.

### Multithreading

Conclusion: useful for background and batch work, but not yet the main live
recognition strategy.

- Background jobs like art prehashing benefit from concurrency.
- The parent app can still get throughput by handling independent work at a
  higher level.
- For single-card live recognition, the dominant costs are still OCR policy and
  fallback behavior rather than a lack of thread-level parallelism around cheap
  stages.
- On Pi 5, extra live-stage concurrency risks more contention and worse tail
  latency before it helps.

Decision:

- keep multithreading for background maintenance and batch workflows
- do not make live per-card recognition depend on internal multithreaded stage
  fan-out yet

### GPU Acceleration

Conclusion: not the right next investment for Pi 5.

- The current OCR stack is RapidOCR ONNXRuntime plus PaddleOCR fallback.
- The measured bottleneck is still OCR decision policy and OCR runtime, not
  image preprocessing.
- The Pi 5 does not offer a simple, low-maintenance GPU path here that looks
  more attractive than continued CPU-side OCR and fallback tuning.

Decision:

- treat GPU acceleration as future research, not a Milestone 11 requirement
- keep prioritizing CPU-friendly OCR policy, ROI analysis, and optional custom
  OCR training investigation first

## Practical Milestone 11 Closeout

At this point Milestone 11 has done what it needed to do:

- it established repeatable measurement
- it identified the real hotspots
- it produced at least one measured optimization pass
- it added variance-aware reporting so outliers are visible
- it closed the multithreading and GPU questions with deployment-aware
  conclusions for Raspberry Pi 5

The remaining performance work from here should be treated as continued
optimization, not as blocked Milestone 11 scaffolding.
