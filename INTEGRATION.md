# Card Engine Integration Guide

This guide is for parent repositories embedding `fuzzy-enigma-card-recognition`
as a submodule or editable dependency. For the desktop debug UI, use
[HOWTO.md](HOWTO.md) instead. For the operational recognition flow and current
mode decision tree, use [docs/mode-pipelines.md](docs/mode-pipelines.md).

## Install Matrix

The base package now includes the image stack required for recognition:

- base recognition: `pip install -e ./third_party/fuzzy-enigma-card-recognition`
- OCR-enabled: `pip install -e ./third_party/fuzzy-enigma-card-recognition[ocr]`
- UI-enabled: `pip install -e ./third_party/fuzzy-enigma-card-recognition[ui]`
- local development: `pip install -e ./third_party/fuzzy-enigma-card-recognition[ocr,ui,dev]`
- engine-only tests: `python -m pytest --engine-only`
- UI-only tests: `python -m pytest --ui-only`

Use the `ocr` extra whenever you expect OCR backends to be available. The `ui`
extra is only needed for the Scryfall-backed random-card UI action and catalog
helpers.

For parent repos, the intended default is:

- install `.[ocr]`
- use the engine API or sorter adapter
- run `pytest --engine-only`

The UI remains optional local tooling and is not required for embedding.

## Parent Quickstart

Concrete end-to-end example:

```powershell
git clone --recurse-submodules https://github.com/your-org/your-parent-app.git
cd your-parent-app

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .\third_party\fuzzy-enigma-card-recognition[ocr]
```

Create a parent-owned config file such as
`config/card-engine/engine.json`:

```json
{
  "catalog_path": "C:/work/your-parent-app/var/card-engine/cards.sqlite3",
  "candidate_count": 5,
  "lazy_group_basic_land_printings": true,
  "recognition_deadline_seconds": 20.0,
  "roi_expand_long_factor": 1.1,
  "roi_expand_short_factor": 1.2
}
```

Then wire your frame into the recognizer:

```python
from pathlib import Path

from card_engine.adapters.sortingmachine import SortingMachineRecognizer
from card_engine.config import load_engine_config

config = load_engine_config(
    str(Path("C:/work/your-parent-app/config/card-engine/engine.json"))
)
recognizer = SortingMachineRecognizer(config=config, auto_track_results=True)

# frame can be a numpy image array, a loaded image-like object, or a path.
result = recognizer.recognize_top_card(frame, mode="greenfield")
print(result.card_name, result.confidence)
```

If you want richer parent-side handling for low-confidence scans:

```python
detailed = recognizer.recognize_top_card(frame, mode="greenfield", detailed=True)
print(detailed.card_name, detailed.confidence)
print(detailed.scryfall_id, detailed.oracle_id)
print(detailed.bbox, detailed.active_roi)
print(detailed.top_k_candidates[:3])
print(detailed.debug)
```

Identifier guidance:

- use `scryfall_id` when the parent needs exact-printing identity
- use `oracle_id` when the parent wants to group same-card printings

For direct offline catalog inspection outside the recognizer flow:

```python
from card_engine.catalog import OfflineCatalogQuery

query = OfflineCatalogQuery.from_sqlite(config.catalog_path)
oracle = query.get_oracle_card("oracle-id-here")
printings = query.printings_for_oracle("oracle-id-here")
```

And from the CLI:

```powershell
.\.venv\Scripts\python.exe scripts\query_offline_catalog.py `
  --catalog C:\work\your-parent-app\var\card-engine\cards.sqlite3 `
  printings-for-name "Sliver Legion"
```

## Path Ownership

Important path rule:

- relative paths like `data/config/engine.json` and `data/catalog/cards.sqlite3`
  are resolved against the parent process working directory
- they are not package-relative
- they are not automatically scoped to the submodule directory

For embedded use, the recommended pattern is:

- parent app owns all mutable paths
- parent app passes absolute config and data paths
- submodule repo stays clean except for committed source, docs, and committed
  ROI config such as `data/config/hash_rois.json`

Practical recommendation:

- set `CARD_ENGINE_CONFIG_PATH` to an absolute parent-owned config path, or
- construct `EngineConfig` directly with parent-owned absolute paths

If your camera framing is not perfectly centered, the parent can also use
`roi_expand_long_factor` and `roi_expand_short_factor` to expand OCR-oriented
regions from their center point. This affects text-reading crops such as title,
type line, and lower text, but it does not change art-match or set-symbol
reference regions.

For live sorter use, the parent should also decide what counts as "too slow to
be useful." The engine now exposes `recognition_deadline_seconds` for that.
The default is `20.0`, which means an over-budget recognition comes back as a
failure result instead of a successful but unacceptably slow answer.

Evaluation tooling uses a looser ceiling by default so a single pathological
card does not pin the whole benchmark. The CLI multiplies the live deadline by
`20.0` unless you override `--benchmark-deadline-multiplier`.

## Data Ownership

Recommended ownership split:

- parent repo/application owns:
  - runtime `engine.json`
  - SQLite catalog files
  - downloaded Scryfall bulk JSON
  - evaluation outputs
  - random-card caches
  - simulated pair databases
  - UI overrides and any other mutable cache files
- recognition submodule owns:
  - source code
  - tests
  - docs
  - committed ROI defaults such as `data/config/hash_rois.json`

This avoids dirty submodule state during normal operation.

The local SQLite catalog is fully offline and is now moving toward a normalized
shape with:

- `oracle_cards` for Oracle-level identity and shared card properties
- `printed_cards` for exact printings and printing-specific metadata

That split is meant to make parent-side querying easier when the parent wants
either exact printings or grouped same-card identities.

The query layer stays intentionally scoped to the paper-only local catalog.
Digital-only printings are filtered out at catalog-build time and do not appear
in these offline query results.

## First-Run Side Effects

The first recognition call may be noticeably slower than later calls.

On first use, the engine may:

- download Scryfall bulk card data
- build or rebuild the local SQLite catalog
- create cache directories on disk

If your parent workflow has a startup phase, it is reasonable to warm the
catalog before the first live recognition request.

## Adapter Notes

`SortingMachineRecognizer` stays backward-compatible by default:

- `recognize_top_card(...)` returns `card_name` plus `confidence`
- pass `detailed=True` to also receive `scryfall_id`, `oracle_id`, bbox, OCR
  lines, candidates, ROI info, debug payload, and the underlying raw
  recognition result

Tracked-pool/session hooks are also available:

```python
from card_engine.operational_modes import ExpectedCard

recognizer.add_expected_card(
    ExpectedCard(name="Island", set_code="M21", collector_number="264")
)
output = recognizer.recognize_top_card(frame, mode="small_pool")
pool_entries = recognizer.get_tracked_pool_entries()
recognizer.clear_tracked_pool()
```

Each tracked-pool entry now includes:

- `name`
- `scryfall_id`
- `oracle_id`
- `set_code`
- `collector_number`

Use these modes as a starting point:

- `greenfield`: open-ended recognition, optionally building tracked pool state
- `small_pool`: constrain recognition to a known candidate pool
- `reevaluation`: bias toward an expected card while still allowing recovery
- `confirmation`: score how strongly the observed card agrees with an expected
  printing

The step-by-step pipeline for each of these modes is documented in
[docs/mode-pipelines.md](docs/mode-pipelines.md).

## Engine / UI Test Boundary

The debug UI is now treated as optional from the test runner's point of view:

- `python -m pytest --engine-only` skips UI-only test modules at collection
  time
- `python -m pytest --ui-only` collects only the UI/debug suite
- the default `python -m pytest` still runs the full repo suite for local
  development

That means parent repos embedding this package can validate the engine,
adapter, and catalog layers without importing or collecting the UI tests unless
they explicitly opt in.

One important nuance: this is an engine/UI boundary in dependency usage, import
surface, and test collection. It is not yet a split into two separately
published Python packages.
