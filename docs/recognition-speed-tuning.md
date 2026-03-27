Delete this eventually

# Recognition Speed Deep Dive

This is a code-path-level plan for reducing recognition latency, not a generic checklist.

## Current reality from measurements

Milestone 11 baseline data already shows the dominant costs:

- open-ended modes are dominated by `secondary_ocr` and `title_ocr`
- constrained modes are dominated by `title_ocr`
- visual tie-break stages are comparatively small

That means speed work should continue to target OCR policy first, then OCR backend/runtime behavior.

## Where latency is created in the current pipeline

## End-to-end path

`recognize_card(...)` currently does this in order:

1. detect + normalize
2. title-first OCR over title-like ROI groups
3. primary candidate match + score
4. optional set-symbol/art rerank
5. optional secondary OCR loop over non-title ROIs
6. re-match + re-score after each secondary ROI until confidence gate says stop

The biggest latency multipliers are:

- number of OCR passes performed (especially secondary loop iterations)
- OCR backend response time per pass
- repeated secondary re-ranking cycles when OCR evidence is weak

## Existing gates that already help

There are useful skip gates already in place:

- constrained modes (`small_pool`, `confirmation`) force `skip_secondary_ocr=True`
- secondary OCR loop is skipped when `should_skip_secondary_ocr(...)` says result is decisive
- visual rerank work is deadline-capped by `max_visual_tiebreak_seconds_per_card`

This is good, but in practice you still pay for title OCR almost always, and open-ended tails still come from fallback/secondary behavior.

## Concrete tuning levers (code-backed)

## 1) Secondary OCR skip thresholds

Current secondary-skip policy is rule-based and confidence-threshold driven.
Important thresholds in `set_symbol.py`:

- `PRIMARY_EXACT_SKIP_CONFIDENCE_THRESHOLD = 0.9`
- `PRIMARY_EXACT_MARGIN_SKIP_THRESHOLD = 0.16`
- `SUPPORTED_FUZZY_SKIP_CONFIDENCE_THRESHOLD = 0.94`
- `SETTLED_NAME_SKIP_CONFIDENCE_THRESHOLD = 0.88`
- `SETTLED_NAME_DIFFERENT_NAME_MARGIN_THRESHOLD = 0.18`

These numbers directly control how often expensive secondary OCR runs. If your production camera/input quality is stable, these can be tuned more aggressively after fixture validation.

## 2) ROI breadth and cycle order

The pipeline resolves ROI groups from `enabled_roi_groups` + layout-derived groups, then iterates title/secondary groups in cycle order.

Default enabled groups include `standard`, `art_match`, `type_line`, `set_symbol`, `lower_text`, and the cycle order still includes extra groups (`adventure`, `transform_back`, `split_*`, `planar_title`) when enabled or layout-selected.

For a narrow card population, cutting ROI breadth is one of the safest ways to reduce OCR invocations.

## 3) Mode strategy (largest low-risk win)

If your parent app has context, prefer:

- `small_pool` when you have a bounded candidate pool
- `confirmation` when validating an expected printing

These modes skip secondary OCR by design and are already much faster in measured baselines.

## 4) Visual rerank budget controls

Visual tie-break is cheap on average but can tail when references are not local.
You can bound this via:

- `max_visual_tiebreak_candidates`
- `max_visual_tiebreak_seconds_per_card`
- `reference_download_timeout_seconds`

Tune these only after OCR policy changes so you do not mask OCR issues with hard caps.

## Deeper experiments to run next (in order)

## Experiment A: Secondary OCR frequency reduction

Goal: reduce secondary OCR invocation rate in open-ended modes.

Method:

- run baseline with current thresholds
- tighten skip thresholds incrementally (one variable at a time)
- track: top-1/set/art accuracy, avg runtime, p95, max runtime, secondary OCR invocation count

Success criteria:

- no statistically meaningful drop in top-1/set/art on your fixture mix
- at least 15-25% reduction in open-ended p95 runtime

## Experiment B: ROI minimization per deployment profile

Goal: remove unnecessary OCR work for your actual card/layout distribution.

Method:

- create profile configs with reduced `enabled_roi_groups` and a narrower `roi_cycle_order`
- benchmark each profile on the same fixture set

Success criteria:

- zero or near-zero top-1 regression
- measurable drop in `title_ocr` and `secondary_ocr` stage averages

## Experiment C: OCR backend stability + warmup

Goal: reduce per-pass OCR variance and cold-start penalties.

Method:

- compare first-N and steady-state runtime distributions
- ensure OCR backend initialization occurs before live recognition bursts

Success criteria:

- reduced runtime stddev and lower p95/max, especially first-card latency

## Experiment D: Tail-focused deadline tuning

Goal: cap pathological outliers without hurting normal cases.

Method:

- progressively lower visual budget/timeouts
- verify outlier reduction without confidence collapse on tie-heavy cards

Success criteria:

- lower p95/max runtime with minimal impact on set/art disambiguation

## Experiment E: Title OCR-specific optimization for constrained modes

Goal: improve `small_pool` / `confirmation` which are mostly title OCR-bound.

Method:

- optimize title OCR path independently from full open-ended pipeline
- evaluate lightweight OCR caching only where frame-to-frame reuse is realistic

Success criteria:

- lower constrained-mode average runtime without confidence drift

## What *not* to do first

- do not start with matcher micro-optimization; current data shows OCR dominates
- do not jump to multithreading/GPU before OCR policy + ROI work is measured
- do not tune many knobs simultaneously; you will lose attribution

## Recommended benchmarking loop

Use consistent fixtures and compare JSON outputs run-to-run:

```bash
python scripts/eval_fixture_set.py \
  --fixtures-dir <fixtures_dir> \
  --operational-modes all \
  --pair-db <pair_db.sqlite3> \
  --json-out <result.json>
```

Track at minimum:

- top-1/set/art accuracy
- average runtime, median, p95, max
- `title_ocr` and `secondary_ocr` average stage timings
- secondary OCR invocation count

## Bottom line

If your goal is materially faster recognition, the highest-yield path is:

1. maximize constrained-mode usage where workflow allows
2. reduce secondary OCR frequency in open-ended modes via threshold tuning
3. reduce ROI breadth/cycle complexity for your card population
4. then tune visual budgets and OCR backend behavior

That sequence is most likely to move both average and tail latency without sacrificing recognition quality.

## Runtime budget policy

The engine now has an explicit per-card runtime budget via
`recognition_deadline_seconds` in `EngineConfig`.

Current intended meaning:

- live recognition that runs past that budget is treated as a failure
- fixture benchmarks inherit the same budget card-by-card, so a benchmark no
  longer counts "correct but unacceptably slow" cards as successes

That makes latency targets visible in normal evaluation output instead of being
only an after-the-fact interpretation of stage timings.

## FAQ: Was the previous approach wrong?

Not wrong, but incomplete.

The earlier documentation correctly emphasized OCR-first optimization, but it did not map the recommendations tightly enough to the exact control points in the code path. The more useful framing is:

- **Step 1:** reduce *how often* OCR runs (`secondary_ocr` gating and ROI breadth)
- **Step 2:** reduce *how expensive each OCR pass is* (backend tuning/warmup)
- **Step 3:** only then optimize non-dominant stages

If you skip Step 1 and Step 2, multithreading alone tends to hide symptoms instead of removing the dominant work.

A concrete example now in the codebase:

- vertical title ROIs no longer pay for a meaningless `0`-degree OCR attempt
- split/planar title OCR can stop early when the rotated `planar_title`
  result is already strong enough that the horizontal `standard` title pass
  would mostly add latency

## FAQ: Can OCR for different regions run in parallel?

Yes, with caveats.

Feasibility:

- title ROI OCR attempts are currently independent calls and can be parallelized
- secondary ROI OCR passes are also independent at the OCR stage

Important caveat in this codebase:

- OCR backends are held in module-level singleton globals (`_RAPID_OCR_INSTANCE`, `_PADDLE_OCR_INSTANCE`) with no explicit locking
- thread safety of the underlying backend objects is not guaranteed by this repository

Practical recommendation:

- parallelize OCR using a **small worker pool** (e.g. 2 workers), but validate backend stability first
- if backend thread safety is uncertain, prefer **process-based** parallelism or one-engine-per-thread initialization strategy
- do not fan out large numbers of parallel OCR calls on Pi-class hardware; memory pressure and contention can erase gains

## FAQ: Can pipeline steps be parallelized?

Partially.

### What is safe/valuable to parallelize

- set-symbol and art rerank can run concurrently once candidate list + crops are ready
- ROI OCR fan-out can run concurrently for the same stage (title set or secondary set)

### What should stay sequential

- detect -> normalize -> crop extraction (hard dependency chain)
- candidate matching/scoring after OCR evidence changes (needs ordered, deterministic updates)
- secondary loop decision logic (`should_skip_secondary_ocr`) since each pass changes the stop condition

### Expected impact

- **Best gains:** overlap visual rerank and selected OCR tasks to reduce tail latency
- **Lower gains:** parallelizing everything blindly; dependencies and shared backends limit scaling

## Concurrency rollout plan (low risk)

1. Add a feature flag for parallel title-ROI OCR only.
2. Run fixture benchmarks and compare top-1/set/art, p95, max, and crash/error rate.
3. If stable, add parallel set-symbol/art rerank.
4. Keep secondary loop mostly sequential; only parallelize OCR extraction if stop-condition semantics remain unchanged.
5. Keep pool size conservative (start with 2 workers) and tune per hardware target.
