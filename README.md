# Fuzzy Enigma Card Recognition

`fuzzy-enigma-card-recognition` is a Python card recognizer meant to live well as a
git submodule inside a larger project.

The intended shape is:

- this repo owns card detection, normalization, OCR, candidate ranking, and
  recognition-specific debugging tools
- the parent repo owns camera capture, sorter orchestration, hardware control,
  and application-specific workflow logic

Today, the repo already exposes a callable recognition API, a thin
`SortingMachineArray`-style adapter, a local catalog pipeline, evaluation
tools, and a desktop debug UI.

## Why Use It As a Submodule

This repo is a good fit when another project needs card recognition without
absorbing the recognition internals directly.

Useful properties:

- small parent-facing surface area
- local SQLite catalog instead of live per-scan catalog lookups
- configurable recognition behavior through `EngineConfig`
- eval tooling for accuracy and confidence tuning
- a debug UI for inspecting failures without writing throwaway scripts

The goal is for the parent project to depend on a recognizer, not on the
internal details of OCR regions, ranking heuristics, or catalog maintenance.

## Current Status

What is usable now:

- `recognize_card(...)` for direct programmatic recognition
- `SortingMachineRecognizer` as a thin adapter for parent projects
- optional detailed adapter results for low-confidence handling and debugging
- automatic local catalog maintenance
- timed fixture and random-sample evaluation
- desktop debug UI for manual inspection

Milestone 9 closeout status:

- paper-name accuracy and confidence validation on larger unseen random samples
- repo-committed ROI tuning and stage-level benchmark reporting
- repeatable operational validation for `greenfield`, `small_pool`,
  `reevaluation`, and `confirmation`

Still ahead:

- split-card and nonstandard-title fallback OCR
- deeper mode/output polish for parent workflows

See [roadmap.md](roadmap.md) for the planned milestones and
[docs/milestone9-closeout.md](docs/milestone9-closeout.md) for the measured
Milestone 9 validation snapshot. For parent-repo wiring, use
[INTEGRATION.md](INTEGRATION.md). For the desktop debug UI, use
[HOWTO.md](HOWTO.md).

## Install

Install options:

- base recognition:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

- OCR-enabled recognition:

```powershell
python -m pip install -e .[ocr]
```

- UI-enabled extras such as the random-card action:

```powershell
python -m pip install -e .[ui]
```

- local development:

```powershell
python -m pip install -e .[ocr,ui,dev]
```

Run tests:

```powershell
python -m pytest
```

The base package now includes the image stack used by recognition. The `ocr`
extra adds OCR backends, and the `ui` extra adds `scrython` for the debug UI's
random-card and Scryfall-backed helper flows.

## Parent Quickstart

Recommended parent-repo locations:

- `third_party/fuzzy-enigma-card-recognition`
- `external/fuzzy-enigma-card-recognition`

Example submodule add:

```powershell
git submodule add https://github.com/schaffer2013/fuzzy-enigma-card-recognition.git third_party/fuzzy-enigma-card-recognition
```

Concrete parent-repo setup:

```powershell
git clone --recurse-submodules https://github.com/your-org/your-parent-app.git
cd your-parent-app

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .\third_party\fuzzy-enigma-card-recognition[ocr]
```

Create a parent-owned config file such as `config/card-engine/engine.json`:

```json
{
  "catalog_path": "C:/work/your-parent-app/var/card-engine/cards.sqlite3",
  "candidate_count": 5,
  "lazy_group_basic_land_printings": true
}
```

Then call the recognizer from the parent app:

```python
from pathlib import Path

from card_engine.adapters.sortingmachine import SortingMachineRecognizer
from card_engine.config import load_engine_config

config = load_engine_config(
    str(Path("C:/work/your-parent-app/config/card-engine/engine.json"))
)
recognizer = SortingMachineRecognizer(config=config, auto_track_results=True)

result = recognizer.recognize_top_card(frame, mode="greenfield")
print(result.card_name, result.confidence)
```

The parent project should ideally do only four things:

1. install this package and its chosen extras
2. provide image frames
3. provide config wiring
4. call the adapter or API

For a fuller integration walkthrough, including path ownership and first-run
catalog behavior, see [INTEGRATION.md](INTEGRATION.md).

## Parent-Facing API

Direct API use:

```python
from card_engine.api import recognize_card
from card_engine.config import EngineConfig

config = EngineConfig(candidate_count=5)
result = recognize_card(frame, config=config)

print(result.best_name, result.confidence)
```

Mode-aware API use:

```python
from card_engine.api import recognize_card
from card_engine.operational_modes import CandidatePool, ExpectedCard

result = recognize_card(frame, mode="greenfield")

expected = ExpectedCard(name="Lightning Bolt", set_code="M11", collector_number="146")
result = recognize_card(frame, mode="reevaluation", expected_card=expected)

pool = CandidatePool.from_records(catalog.exact_lookup("Island"))
result = recognize_card(frame, mode="small_pool", candidate_pool=pool)
```

Today:

- `default` and `greenfield` are explicit API modes
- `small_pool` is a real constrained mode
- `reevaluation` biases the expected card while still allowing disagreement
  recovery
- `confirmation` returns expected-printing confidence plus contradiction details

Session/tracked-pool use:

```python
from card_engine.operational_modes import ExpectedCard
from card_engine.session import RecognitionSession

session = RecognitionSession(auto_track_results=True)

result = session.recognize(frame, mode="greenfield")
pool = session.get_tracked_pool()

result = session.recognize(frame, mode="small_pool")
session.add_expected_card(ExpectedCard(name="Island", set_code="M21", collector_number="264"))
session.clear_tracked_pool()
```

The tracked pool now lives in the engine/session layer and is exposed through
the sorter adapter.

Thin adapter use:

```python
from card_engine.adapters.sortingmachine import SortingMachineRecognizer
from card_engine.config import EngineConfig
from card_engine.operational_modes import ExpectedCard

recognizer = SortingMachineRecognizer(
    config=EngineConfig(candidate_count=5),
    auto_track_results=True,
)
output = recognizer.recognize_top_card(frame)

print(output.card_name, output.confidence)

recognizer.add_expected_card(
    ExpectedCard(name="Island", set_code="M21", collector_number="264")
)
pool_entries = recognizer.get_tracked_pool_entries()
output = recognizer.recognize_top_card(frame, mode="small_pool")
recognizer.clear_tracked_pool()
```

Inline sorter/session example:

```python
from card_engine.adapters.sortingmachine import SortingMachineRecognizer
from card_engine.operational_modes import ExpectedCard

recognizer = SortingMachineRecognizer(auto_track_results=True)

output = recognizer.recognize_top_card(frame, mode="greenfield")
print(output.card_name, output.confidence)

recognizer.add_expected_card(
    ExpectedCard(name="Island", set_code="M21", collector_number="264")
)
pool_entries = recognizer.get_tracked_pool_entries()
output = recognizer.recognize_top_card(frame, mode="small_pool")
recognizer.clear_tracked_pool()
```

Current adapter contract:

- input: a frame-like object or image path accepted by `recognize_card(...)`
- output: card name plus confidence
- optional richer output with `scryfall_id`, `oracle_id`, bbox, OCR,
  candidates, ROI info, and debug data via `detailed=True`
- tracked-pool inspection/seed/clear hooks for sorter workflows
- optional mode-aware recognition via the same adapter instance

Detailed adapter use:

```python
detailed = recognizer.recognize_top_card(frame, mode="greenfield", detailed=True)

print(detailed.card_name, detailed.confidence)
print(detailed.scryfall_id, detailed.oracle_id)
print(detailed.bbox, detailed.active_roi)
print(detailed.top_k_candidates[:3])
print(detailed.debug)
```

When the parent can consume both Scryfall identifiers:

- use `scryfall_id` for exact printing identity
- use `oracle_id` for grouping same-card printings across sets

Tracked-pool entries now also preserve those identifiers, so parent-side pool
inspection can work with exact-printing IDs or Oracle-group IDs directly.

The adapter lives in [sortingmachine.py](src/card_engine/adapters/sortingmachine.py).

## Configuration

Runtime configuration is defined by `EngineConfig` in
[config.py](src/card_engine/config.py).

Config can come from, in practice:

- direct construction in Python
- `CARD_ENGINE_CONFIG_PATH`
- `data/config/engine.json`

A starter config file is included at
[engine.sample.json](data/config/engine.sample.json).

When loading from disk, unknown keys are ignored and missing keys fall back to
the built-in defaults.

Path behavior is important for parent integrations:

- relative paths are resolved against the current working directory of the
  calling process
- they are not package-relative to this submodule
- for embedded use, prefer absolute parent-owned paths

The repo-local `data/...` defaults are mainly convenience defaults for
standalone repo usage and the debug UI.

Current `EngineConfig` fields:

- `catalog_path`: path to the local SQLite catalog. Default:
  `data/catalog/cards.sqlite3`.
- `debug_enabled`: reserved debug toggle. Present in config today, but not yet
  deeply wired into every stage.
- `candidate_count`: number of top candidates returned in the final result.
  The recognizer may keep a wider internal pool before trimming to this count.
- `detection_min_area_ratio`: minimum contour-area ratio for card detection
  heuristics.
- `max_image_edge`: maximum normalized image edge size used before downstream
  processing.
- `enabled_roi_groups`: ROI groups the recognizer is allowed to use.
- `roi_cycle_order`: deterministic order for trying ROI groups.
- `layout_heuristics_enabled`: toggle for layout-driven ROI heuristics.
- `lazy_group_basic_land_printings`: performance optimization that collapses
  same-name basic-land printings to a default printing before expensive visual
  tie-break work.
- `lazy_default_printing_by_name`: broader performance optimization that
  collapses all same-name printings to a default printing before expensive
  visual tie-break work.
- `max_visual_tiebreak_candidates`: hard cap on how many candidates are sent
  into set-symbol and art-region comparison.
- `max_visual_tiebreak_seconds_per_card`: per-card time budget for visual
  tie-break work.
- `reference_download_timeout_seconds`: timeout for fetching uncached reference
  images used by visual tie-break steps.

The config surface is still growing. As new mode-aware and integration-facing
features land, this section should be kept in sync with `EngineConfig` so the
README remains the parent-project-facing source of truth.

## Catalog Behavior

The engine uses a local SQLite catalog. On demand, it can:

- detect a missing catalog
- refresh stale catalog data
- rebuild malformed or schema-mismatched catalogs

Catalog maintenance lives in
[maintenance.py](src/card_engine/catalog/maintenance.py).

The offline catalog is now structured around:

- `oracle_cards` for rules-level card identity keyed by `oracle_id`
- `printed_cards` for exact printings keyed by `scryfall_id`

The current recognizer still reads through a compatibility view so the storage
layer can evolve without forcing a full matcher rewrite at the same time.

Default paths:

- SQLite catalog: `data/catalog/cards.sqlite3`
- bulk source JSON: `data/catalog/default-cards.json`

First-run note:

- the first recognition call may download Scryfall bulk data
- it may build or rebuild the local SQLite catalog
- because of that, first use is often slower than steady-state recognition

## Debug UI

The repo also includes a desktop debug UI for fixture browsing and recognition
inspection. This is useful both for standalone debugging and when the engine is
embedded inside another project.

Launch it with:

```powershell
python -m card_engine.ui --fixtures-dir data\fixtures
```

The UI currently supports:

- fixture browsing
- bounding-box overlay review
- OCR and candidate inspection
- ROI cycling for atypical layouts
- re-evaluation after manual bbox or ROI edits
- random-card fetching for manual spot checks

The hash-related ROI bounds for reference-image caching live in
`data/config/hash_rois.json`, so they are easy to review and commit in the
repo. Reference art and set-symbol hashes are cached only for ideal/reference
card images, and each cache is invalidated automatically when the committed ROI
bounds for that specific hash region change.

The fuller UI walkthrough is in
[HOWTO.md](HOWTO.md).

## Evaluation Tools

Evaluate a fixture folder:

```powershell
python scripts\eval_fixture_set.py --fixtures-dir data\cache\random_cards
```

Run a fresh timed random evaluation:

```powershell
python scripts\eval_fixture_set.py `
  --random-time-limit-minutes 10 `
  --random-output-dir data\sample_outputs\random_eval_cards `
  --json-out data\sample_outputs\random-eval-summary.json
```

Random fixture downloads now request `game:paper lang:en` from Scryfall by
default so the sample set stays aligned with the repo's English-only,
paper-card recognition scope.

Compare a fresh run against a prior saved summary:

```powershell
python scripts\eval_fixture_set.py `
  --fixtures-dir data\cache\random_cards `
  --compare-to data\sample_outputs\random-eval-summary.json `
  --json-out data\sample_outputs\random-eval-summary-new.json
```

Run the same fixture set across the built-in benchmark modes:

```powershell
python scripts\eval_fixture_set.py `
  --fixtures-dir data\sample_outputs\random_eval_cards `
  --benchmark-modes all `
  --json-out data\sample_outputs\random-eval-benchmark-modes.json
```

Simulated benchmark and fixture evaluations also update a SQLite pair-tracking
database at `data/cache/simulated_card_pairs.sqlite3` by default. Each run
upserts `(expected_card_id, actual_card_id)` with a running `seen_count`,
including correct recognitions, and keeps only the 10,000 most recently seen
unique pairs. Override the location with `--pair-db`.

To turn repeated mismatches into a reusable regression fixture folder:

```powershell
python scripts\build_regression_fixture_set.py `
  --fixtures-dir data\sample_outputs\random_eval_cards `
  --output-dir data\cache\regression_fixtures `
  --max-cases 12 `
  --min-seen-count 3
```

That copies the matching image fixtures plus sidecars and writes a
`regression_manifest.json` describing the expected cards and their repeated
wrong predictions.

The eval workflow reports:

- top-1 and top-5 name accuracy
- set and exact-printing accuracy
- confidence summaries
- average runtime and stage timing summaries
- confidence calibration bins and ECE
- ROI usage and error-class breakdowns

When `--compare-to` is provided, the script also prints metric deltas,
calibration-gap deltas, and average stage-timing deltas versus the saved
baseline summary.

When `--benchmark-modes` contains more than one mode, the script evaluates the
same fixtures across each named config mode and reports accuracy separately for
each one. Today the built-in mode suite is:

- `default`
- `lazy_basic_lands`
- `lazy_all_printings`

## Repository Layout

Important paths:

- `src/card_engine/api.py`: main recognition entry point
- `src/card_engine/adapters/sortingmachine.py`: thin parent-project adapter
- `src/card_engine/catalog/`: local catalog build and maintenance
- `src/card_engine/ui/`: desktop debug UI
- `scripts/eval_fixture_set.py`: evaluation entry point
- `INTEGRATION.md`: parent-repo integration guide
- `HOWTO.md`: UI/debug workflow guide
- `roadmap.md`: implementation plan and milestone status

## Data Ownership

For embedded use, a clean ownership split is:

- parent repo/application owns mutable runtime data such as `engine.json`,
  SQLite catalogs, downloaded bulk JSON, pair DBs, eval outputs, and cache
  directories
- this submodule owns code, tests, docs, and committed defaults such as
  `data/config/hash_rois.json`

That pattern avoids routine dirty submodule state from caches or local runtime
artifacts.

## Limitations

Current limitations worth knowing before parent-project adoption:

- deeper refinement of mode-specific confidence semantics is still in progress
- first-run catalog setup can make the initial recognition call slower
- split-card/nonstandard-title fallback OCR is still future expansion

If you want the shortest answer on readiness: this repo is already usable as a
submodule for direct recognition integration, but it is still moving from
"embeddable" toward "fully polished integration component."
