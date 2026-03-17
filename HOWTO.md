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
Cycles the active ROI label used by the UI state. This is useful for future
layout-aware OCR/debug flows and already updates the displayed state.

`Toggle BBox`
Shows or hides the recognition bounding box overlay on top of the preview.

`Refresh`
Rescans the fixture directory passed at launch time and reloads the fixture
list from disk.

`Random Card`
Fetches a random card image using Scrython, stores it under
`data/cache/random_cards`, inserts it at the top of the fixture list, and
immediately runs recognition on it.

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

## Preview Panel

The `Preview` panel shows the current image if Tk can render the file format
directly.

If preview rendering is not available for that format, the panel shows a
fallback message with the known image metadata instead of crashing.

When `Toggle BBox` is enabled and the recognizer returns a bounding box, the UI
draws a green overlay rectangle on top of the preview.

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
- top candidate list

Right now the recognition pipeline is still mostly scaffold logic, so this
panel is useful for tracing current behavior more than judging model accuracy.

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

## Random Card Notes

The random-card button depends on `scrython`.

If `scrython` is not installed, the button will fail gracefully and the Status
panel will explain why.

Random downloads are cached locally so you can inspect them again without
having to keep them only in memory.

## Current Limitations

- There is only one page today.
- The OCR and matching pipeline are still early-stage placeholders.
- Some image formats can be recognized from file metadata without being
  previewable in Tk.
- The random-card action runs synchronously, so it may briefly pause the UI
  while downloading.
