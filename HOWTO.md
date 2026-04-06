# Card Engine UI HOWTO

## Purpose

The current UI is a single debug window for browsing fixture images, previewing
the selected image, and seeing the engine's current recognition output.

This file is intentionally UI-focused. If you are embedding the recognizer into
another repository, use [INTEGRATION.md](INTEGRATION.md) for adapter wiring,
config ownership, parent-owned data directories, and first-run catalog notes.
For the recognition-mode pipeline and decision tree, use
[docs/mode-pipelines.md](docs/mode-pipelines.md).

The committed hash ROI bounds now live in `data/config/hash_rois.json`. The
reference-image caches for art and set-symbol hashing are tied to those ROI
bounds and are automatically cleared for that specific ROI if the committed
bounds change.

Launch it with:

```powershell
.\.venv\Scripts\python.exe -m card_engine.ui --fixtures-dir data\fixtures
```

Fresh setup and later updates can use the repo scripts directly:

```powershell
.\scripts\setup_dev_env.ps1
.\scripts\setup_dev_env.ps1 -Update
```

```bash
./scripts/setup_dev_env.sh
./scripts/setup_dev_env.sh --update
```

That script flow should be treated as the required setup path for end-user or
tester machines. If you want the shipped UI, OCR, and optional Moss tooling to
match the repo's supported runtime, use the setup script and rerun it in update
mode after pulls.

If you want the random-card button to work, install the UI extra first:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .[ui]
```

For full local development with OCR backends and tests:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .[ocr,ui,moss,dev]
```

If you only want the engine suite during local work, use:

```powershell
.\.venv\Scripts\python.exe -m pytest --engine-only
```

If you only want the UI/debug suite, use:

```powershell
.\.venv\Scripts\python.exe -m pytest --ui-only
```

For fixture-level accuracy checks outside the UI, run:

```powershell
.\.venv\Scripts\python.exe scripts\eval_fixture_set.py --fixtures-dir data\cache\random_cards
```

For split-card investigations, you can build the offline split fixture pool and
then summarize an operational benchmark by split family:

```powershell
.\.venv\Scripts\python.exe scripts\build_split_fixture_set.py
.\.venv\Scripts\python.exe scripts\report_split_family_metrics.py `
  --report-json data\sample_outputs\split_layout_operational_full.json `
  --csv-out data\sample_outputs\split_layout_operational_by_family.csv
```

For a fresh random accuracy run with a 10-minute cap, use:

```powershell
.\.venv\Scripts\python.exe scripts\eval_fixture_set.py `
  --random-time-limit-minutes 10 `
  --random-output-dir data\sample_outputs\random_eval_cards `
  --json-out data\sample_outputs\random-eval-summary.json
```

Random fixture downloads request `game:paper lang:en` from Scryfall by default
so the saved sample set matches the English-only local catalog and avoids
digital-only card variants.

To override engine behavior without editing code, create `data\config\engine.json`
or point `CARD_ENGINE_CONFIG_PATH` at a JSON file. A starter example lives at
`data\config\engine.sample.json`.

Relative paths in config remain working-directory relative. For embedded parent
apps, prefer absolute parent-owned paths instead of relying on the repo-local
`data\...` defaults.

Useful lazy optimization toggles include:

- `lazy_group_basic_land_printings`: collapse same-name basic lands to one
  default printing before visual tie-break work
- `lazy_default_printing_by_name`: collapse every card name to one default
  printing before visual tie-break work
- `max_visual_tiebreak_candidates`: cap how many near-tied printings enter the
  set-symbol and art comparison steps
- `max_visual_tiebreak_seconds_per_card`: stop visual tie-break work once a
  card has spent this much time in those steps
- `reference_download_timeout_seconds`: cap per-reference download waits during
  visual comparisons
- `roi_expand_long_factor` / `roi_expand_short_factor`: expand OCR-oriented ROI
  crops outward from their center point without changing committed ROI defaults
- `recognition_deadline_seconds`: treat over-budget recognitions as failures
  instead of successful but too-slow results
- `--benchmark-deadline-multiplier`: let eval runs use a larger per-card
  ceiling than live recognition, defaulting to `20x`

You can also try that live from the CLI:

```powershell
.\.venv\Scripts\python.exe -m card_engine.ui --roi-expand 1.1
.\.venv\Scripts\python.exe scripts\eval_fixture_set.py --fixtures-dir data\fixtures --roi-expand 1.1 1.3
```

This only affects OCR-style crops such as title, type line, and lower text. It
does not expand art-match or set-symbol regions.

The UI remains optional tooling. Parent repos that only embed the recognizer do
not need to use this guide, install the `ui` extra, or collect the UI test
suite.

## Integration Note

The sorter-facing adapter and tracked-session workflow live outside the UI.
Use [INTEGRATION.md](INTEGRATION.md) for:

- `SortingMachineRecognizer` examples
- `detailed=True` adapter output
- tracked-pool/session usage
- `scryfall_id` / `oracle_id` adapter and pool identifiers
- parent-owned config and data-directory recommendations
- first-run catalog side effects

## Main Window

There is one page today: the main debug window.

It is split into four functional areas:

1. Toolbar across the top.
2. Fixture browser on the left.
3. Image preview in the center.
4. Detail panels on the right.

## Toolbar

`Prev`
Moves to the previous fixture in the list and refreshes preview and
recognition.

`Next`
Moves to the next fixture in the list and refreshes preview and recognition.

`Cycle ROI`
Cycles the active ROI label used by the UI state. This updates the displayed
overlay only and does not rerun recognition.

`Toggle BBox`
Shows or hides the recognition bounding box overlay on top of the preview.

`Refresh`
Rescans the fixture directory passed at launch time and reloads the fixture
list from disk.

`Re-evaluate`
Runs recognition again for the currently selected fixture, using any saved bbox
or ROI edits that are currently in effect.

`Random Card`
Fetches a random card image using Scrython, stores it under
`data/cache/random_cards`, inserts it at the top of the fixture list, prunes
older random-card fixtures beyond the cache cap, and immediately runs
recognition on it.

`Reset BBox`
Clears the saved manual bbox/quad override for the selected fixture.

`Reset ROI`
Clears the saved global override for the currently active ROI group.

`Fixture Count`
The label at the far right shows how many fixture images are currently loaded
into the browser.

## Fixture Browser

The `Fixtures` panel lists every supported image file found under the selected
fixture directory.

Supported file types currently include:

- `png`
- `jpg`
- `jpeg`
- `gif`
- `bmp`
- `tif`
- `tiff`
- `webp`

Selecting an item in the list does three things:

1. Loads image metadata.
2. Runs the current recognition pipeline on that file.
3. Refreshes the preview and right-hand panels.

If catalog maintenance or recognition is doing non-trivial work, the UI shows
a splash/progress window instead of silently blocking.

## Preview Panel

The `Preview` panel shows the current image if Tk can render the file format
directly.

If preview rendering is not available for that format, the panel shows a
fallback message with the known image metadata instead of crashing.

When `Toggle BBox` is enabled and the recognizer returns a bounding box, the UI
draws a green overlay polygon on top of the preview.

You can also:

- drag green handles to adjust the detected card quad
- drag orange handles to adjust the active ROI rectangle
- keep ROI rectangles axis-aligned
- persist those edits across restarts
- click `Re-evaluate` when you want those edits applied to recognition

## Fixture Details Panel

The `Fixture Details` panel shows:

- file name
- full path
- current index in the fixture list
- active ROI label
- whether bbox overlay is enabled
- file size
- detected image format
- detected image dimensions

This panel is the quickest way to confirm what file the UI is actually using.

## Recognition Panel

The `Recognition` panel shows the current engine output for the selected image.

It includes:

- best match name
- recognized set abbreviation
- confidence
- active ROI
- tried ROI list
- detected bounding box
- OCR lines
- per-ROI OCR text and backend
- top candidate list

If recognition fails, this panel now shows the failure message instead of
falling back to a misleading empty-state message.

## Status Panel

The `Status` panel is the app activity log for the current selection.

It shows:

- selected fixture name
- current ROI preset
- bbox overlay state
- the latest status message, such as refreshes, selection changes, random-card
  fetch failures, or recognition refreshes

## Footer

The footer is a compact reminder of the main controls.

Current shortcuts:

- `Left Arrow`: previous fixture
- `Right Arrow`: next fixture
- `R`: cycle ROI
- `B`: toggle bbox
- `Escape`: reset bbox for the selected fixture

Changing the active ROI, toggling overlays, or dragging ROI handles does not
rerun recognition automatically anymore.

## Random Card Notes

The random-card button depends on `scrython`.

If `scrython` is not installed, the button will fail gracefully and the Status
panel will explain why.

Random downloads are cached locally so you can inspect them again without
having to keep them only in memory.

The random-card cache is capped automatically at 60 cards so it does not grow
forever. Older random-card image-plus-sidecar pairs are pruned, keeping the
newest downloads.

## Evaluation Workflow

Use the evaluation script when you want repeatable accuracy metrics on a folder
of fixtures.

Example:

```powershell
.\.venv\Scripts\python.exe scripts\eval_fixture_set.py `
  --fixtures-dir data\cache\random_cards `
  --json-out data\sample_outputs\eval-summary.json
```

To compare a tuning candidate against a prior saved baseline summary:

```powershell
.\.venv\Scripts\python.exe scripts\eval_fixture_set.py `
  --fixtures-dir data\cache\random_cards `
  --compare-to data\sample_outputs\eval-summary-baseline.json `
  --json-out data\sample_outputs\eval-summary-candidate.json
```

To benchmark the same fixture set across all built-in config modes:

```powershell
.\.venv\Scripts\python.exe scripts\eval_fixture_set.py `
  --fixtures-dir data\sample_outputs\random_eval_cards `
  --benchmark-modes all `
  --json-out data\sample_outputs\eval-benchmark-modes.json
```

These simulated evaluations also populate `data/cache/simulated_card_pairs.sqlite3`
by default so you can mine repeated expected-vs-actual printing pairs later.
The database keeps `expected_card_id`, `actual_card_id`, and `seen_count`,
including correct matches, and evicts the oldest unique pairs beyond 10,000.
Use `--pair-db` to point at a different database file.

To export the most repeated mismatches into a curated local regression fixture
folder:

```powershell
.\.venv\Scripts\python.exe scripts\build_regression_fixture_set.py `
  --fixtures-dir data\sample_outputs\random_eval_cards `
  --output-dir data\cache\regression_fixtures `
  --max-cases 12 `
  --min-seen-count 3
```

That command copies each matching image fixture and sidecar into the output
folder and writes `regression_manifest.json` so you can see which expected
printings and wrong predictions the curated set is meant to cover.

The script currently reports:

- fixture count
- scored fixture count
- set-scored fixture count
- art-scored fixture count
- name top-1 accuracy
- name top-5 accuracy
- set accuracy
- art accuracy
- average confidence
- average runtime in seconds
- expected calibration error (ECE)
- confidence-bin calibration breakdown
- average stage timings from the recognition debug payload
- ROI usage
- error-class counts
- a short list of top mismatches

Expected names come from sidecar metadata when available, with a filename
fallback for cached random-card images. Set accuracy uses the expected set code
from the sidecar. Art accuracy means exact printing accuracy, using the
expected set code plus collector number from the sidecar.

When you use `--random-time-limit-minutes`, the script fetches and evaluates
random cards until the time budget is exhausted. The deadline is enforced both
between cards and inside recognition's expensive visual tie-break path, so the
final card is now bounded instead of running indefinitely on pathological
same-name pools.

For confidence tuning, compare each bin's `avg_confidence` to its actual
`accuracy`. High-confidence bins with noticeably lower realized accuracy are
the first place to trim or rebalance scoring bonuses. When you use
`--compare-to`, the CLI also shows whether those calibration gaps improved or
regressed relative to the baseline run.

When you use `--benchmark-modes all`, the script runs the same saved fixtures
through each benchmark mode and reports separate accuracy lines for each mode
instead of mixing them together.

A concise benchmark/profile snapshot for the Milestone 9 closeout lives in
[docs/milestone9-closeout.md](docs/milestone9-closeout.md).

## Recognition Flow Notes

The current recognition flow is moving toward a Milestone 9 fast path:

1. OCR the title region first.
   For split layouts, start with the narrow vertical title strip.
2. Use the set-symbol ROI as a lightweight visual tie-breaker for near-tied
   title candidates, using a refined symbol fingerprint rather than a full-card
   image comparison.
3. For split layouts whose narrow strip is weak, fall back to rotated
   whole-card OCR before the generic support ROIs.
4. If the set symbol is still too weak for same-name printings, use the
   `art_match` ROI as a second visual tie-breaker over the same near-tied
   candidates.
5. Only run the remaining ROIs such as `type_line` and `lower_text` if the
   title-plus-visual evidence is still not confident enough.

## Current Limitations

- There is only one page today.
- Some image formats can be recognized from file metadata without being
  previewable in Tk.
- The random-card action runs synchronously, so it may briefly pause the UI
  while downloading.
- The evaluation script only scores fixtures when it can infer an expected
  name from sidecar metadata or filename.
