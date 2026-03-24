# Card Engine Integration Guide

This guide is for parent repositories embedding `fuzzy-enigma-card-recognition`
as a submodule or editable dependency. For the desktop debug UI, use
[HOWTO.md](HOWTO.md) instead.

## Install Matrix

The base package now includes the image stack required for recognition:

- base recognition: `pip install -e ./third_party/fuzzy-enigma-card-recognition`
- OCR-enabled: `pip install -e ./third_party/fuzzy-enigma-card-recognition[ocr]`
- UI-enabled: `pip install -e ./third_party/fuzzy-enigma-card-recognition[ui]`
- local development: `pip install -e ./third_party/fuzzy-enigma-card-recognition[ocr,ui,dev]`

Use the `ocr` extra whenever you expect OCR backends to be available. The `ui`
extra is only needed for the Scryfall-backed random-card UI action and catalog
helpers.

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
  "lazy_group_basic_land_printings": true
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
print(detailed.bbox, detailed.active_roi)
print(detailed.top_k_candidates[:3])
print(detailed.debug)
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
- pass `detailed=True` to also receive bbox, OCR lines, candidates, ROI info,
  debug payload, and the underlying raw recognition result

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

Use these modes as a starting point:

- `greenfield`: open-ended recognition, optionally building tracked pool state
- `small_pool`: constrain recognition to a known candidate pool
- `reevaluation`: bias toward an expected card while still allowing recovery
- `confirmation`: score how strongly the observed card agrees with an expected
  printing
