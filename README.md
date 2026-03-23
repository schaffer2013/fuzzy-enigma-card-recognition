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
- automatic local catalog maintenance
- timed fixture and random-sample evaluation
- desktop debug UI for manual inspection

What is still being hardened:

- confidence tuning on larger unseen random samples
- some crop-quality and non-title tie-break improvements
- more complete integration docs and example configuration
- operational constrained modes for sorter workflows

See [roadmap.md](roadmap.md) for the planned milestones.

## Install

Basic editable install:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
```

If you want the random-card UI action or Scryfall-backed catalog helpers:

```powershell
python -m pip install -e .[dev,ui]
```

Run tests:

```powershell
python -m pytest
```

## Submodule Integration

Recommended parent-repo locations:

- `third_party/fuzzy-enigma-card-recognition`
- `external/fuzzy-enigma-card-recognition`

Example submodule add:

```powershell
git submodule add https://github.com/schaffer2013/fuzzy-enigma-card-recognition.git third_party/fuzzy-enigma-card-recognition
```

The parent project should ideally do only four things:

1. install this package and its chosen extras
2. provide image frames
3. provide config wiring
4. call the adapter or API

## Parent-Facing API

Direct API use:

```python
from card_engine.api import recognize_card
from card_engine.config import EngineConfig

config = EngineConfig(candidate_count=5)
result = recognize_card(frame, config=config)

print(result.best_name, result.confidence)
```

Thin adapter use:

```python
from card_engine.adapters.sortingmachine import SortingMachineRecognizer
from card_engine.config import EngineConfig

recognizer = SortingMachineRecognizer(
    config=EngineConfig(candidate_count=5)
)
output = recognizer.recognize_top_card(frame)

print(output.card_name, output.confidence)
```

Current adapter contract:

- input: a frame-like object or image path accepted by `recognize_card(...)`
- output: card name plus confidence

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

Default paths:

- SQLite catalog: `data/catalog/cards.sqlite3`
- bulk source JSON: `data/catalog/default-cards.json`

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

Fetched and loaded fixture images now keep a one-time `image_sha256` in their
sidecar metadata. Saved card bounds are persisted by that hash in
`data/config/fixture_bboxes.json`, so the default bbox coordinates can be
committed into the repo. The observed set-symbol and art-match fingerprints are
cached in the image sidecar and automatically dropped whenever the saved
bbox/quad changes.

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
- `roadmap.md`: implementation plan and milestone status

## Limitations

Current limitations worth knowing before parent-project adoption:

- constrained operational modes such as small-pool, re-evaluation, and
  confirmation are planned but not finished
- the adapter surface is intentionally thin and currently only returns card
  name plus confidence
- Milestone 8 integration docs and example configuration are still being
  completed
- Milestone 9 accuracy hardening is still in progress

If you want the shortest answer on readiness: this repo is already usable as a
submodule for direct recognition integration, but it is still moving from
"embeddable" toward "fully polished integration component."
