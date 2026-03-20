# Card Engine UI HOWTO

## Purpose

The current UI is a single debug window for browsing fixture images, previewing
the selected image, and seeing the engine's current recognition output.

Launch it with:

```powershell
.\.venv\Scripts\python.exe -m card_engine.ui --fixtures-dir data\fixtures
```

If you want the random-card button to work, install the UI extra first:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .[ui]
```

For fixture-level accuracy checks outside the UI, run:

```powershell
.\.venv\Scripts\python.exe scripts\eval_fixture_set.py --fixtures-dir data\cache\random_cards
```

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
`data/cache/random_cards`, inserts it at the top of the fixture list, and
immediately runs recognition on it.

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

## Evaluation Workflow

Use the evaluation script when you want repeatable accuracy metrics on a folder
of fixtures.

Example:

```powershell
.\.venv\Scripts\python.exe scripts\eval_fixture_set.py `
  --fixtures-dir data\cache\random_cards `
  --json-out data\sample_outputs\eval-summary.json
```

The script currently reports:

- fixture count
- scored fixture count
- top-1 accuracy
- top-5 accuracy
- average confidence
- ROI usage
- error-class counts
- a short list of top mismatches

Expected names come from sidecar metadata when available, with a filename
fallback for cached random-card images.

## Recognition Flow Notes

The current recognition flow is moving toward a Milestone 9 fast path:

1. OCR the title region first.
2. Use the set-symbol ROI as a lightweight visual tie-breaker for top title
   candidates.
3. Only run the remaining ROIs such as `type_line` and `lower_text` if the
   title-plus-set-symbol evidence is still not confident enough.

## Current Limitations

- There is only one page today.
- Some image formats can be recognized from file metadata without being
  previewable in Tk.
- The random-card action runs synchronously, so it may briefly pause the UI
  while downloading.
- The evaluation script only scores fixtures when it can infer an expected
  name from sidecar metadata or filename.
