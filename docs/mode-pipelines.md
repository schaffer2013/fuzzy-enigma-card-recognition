# Mode Pipelines

This document describes the current recognition pipeline at a practical level:

- what every recognition request does
- how the operational modes differ
- where the main decision points are
- what a more granular timing study would likely measure next

It is intentionally higher level than the implementation, but it follows the
current engine behavior closely enough to be useful for parent-repo design and
benchmark interpretation.

## Shared Pipeline

Every mode starts with the same broad stages:

1. Prepare the image input.
   The engine accepts a path, an image-like object, or a frame-like object.

2. Load the local catalog.
   This is the offline SQLite card catalog.

3. Detect the card bounds.
   The engine finds the card region inside the input image.

4. Normalize the card image.
   The card is rectified into a normalized card view and the ROI crops are
   prepared.

5. Try title-first OCR.
   The engine starts with title-oriented ROIs such as `standard` or
   `planar_title`, depending on layout.

6. Match OCR text against the catalog.
   The OCR text is used to assemble a ranked candidate list.

7. Optionally use visual tie-breakers.
   The set-symbol ROI and art ROI may rerank near-tied candidates.

8. Score the candidates.
   The engine chooses the best candidate and final confidence.

9. Optionally run a slower fallback pass.
   If the first title read is still not decisive enough, the engine may read
   additional ROIs such as `type_line` and `lower_text` and rerank again.

## Core Decision Tree

At a high level, the current shared flow is:

1. OCR the title-oriented ROI for the layout.
2. Build candidate rankings from that OCR result.
3. If the candidate pool is near-tied, try the set symbol.
4. If the same-name printing tie is still unresolved, try the art ROI.
5. Score the result.
6. If the result is still not decisive enough, do the slower fallback OCR on
   additional ROIs and rerank inside the already plausible candidate set.
   For split layouts, the expensive rotated whole-card fallback is only used
   when the first split-title read is still weak or noisy enough that it may
   be worth rescuing.
7. Stop early once the engine has enough evidence.

Important practical point:

- the expensive cases are usually not caused by card detection or
  normalization
- they happen when the title read is ambiguous enough that the engine falls
  into the slower fallback path

## Layout-Specific Title Behavior

The title-first stage is layout-aware.

Today, the important families are:

- `normal`: starts from the standard horizontal title band
- `planar`: starts from a vertical title region and tries rotated OCR
- `split`: starts from a vertical title region and can fall back to a rotated
  whole-card title search
- `adventure`: can use the dedicated adventure title area
- `transform` and `modal_dfc`: can use the back-face title area

For split and planar-style titles, rotated OCR matters a lot. The engine may
try multiple rotations before choosing the best OCR result.

## Greenfield

`greenfield` is the open-ended recognition path.

Use it when the parent does not yet know the likely card or candidate pool.

Pipeline:

1. Run the shared pipeline from the full catalog.
2. Let title OCR search broadly.
3. Use visual tie-breakers only on the strongest candidate subset.
4. If still uncertain, use slower fallback OCR on additional ROIs.
5. Return the best open-ended match.

Decision shape:

1. Is the first title read decisive enough?
   If yes, score and stop.
2. For split layouts, if the narrow title strip is weak, try rotated whole-card
   fallback OCR before generic support ROIs. If the first split-title read is
   already a clean exact hit, skip that whole-card rescue path.
3. If not, can the set symbol or art ROI break the tie?
   If yes, score and stop.
4. If not, run the slower supporting ROIs and rerank.

Operational meaning:

- best for a new pile or an unknown top card
- also the mode most likely to hit the expensive fallback path

## Small Pool

`small_pool` is the constrained recognition path.

Use it when the parent already has a known candidate pool, or when the engine
session has built one from earlier scans.

Pipeline:

1. Start from the shared pipeline.
2. Restrict matching to the supplied or tracked pool.
3. Prefer early exits once the constrained pool is decisive.
4. Skip unnecessary broader recovery work.

Decision shape:

1. Does the title read already identify the winner inside the pool?
   If yes, stop.
2. For split layouts, if the narrow title strip is weak, use the rotated
   whole-card split fallback before broader support ROIs.
3. If not, can visual evidence break the tie inside the pool?
   If yes, stop.
4. If not, use the remaining slower support signals.

Operational meaning:

- intended for repeated pile sorting where the parent already knows the local
  context
- usually much faster than `greenfield`

## Reevaluation

`reevaluation` is expected-card-aware recognition that is still allowed to
disagree.

Use it when the parent has an expected card but wants correction if the input
does not really match it.

Pipeline:

1. Run the shared recognition path.
2. Apply an expected-card bias to the candidate list.
3. Keep the ability to overturn the expectation if the observed evidence is
   materially stronger for another card.

Decision shape:

1. Is the expected card already among the plausible candidates?
   If yes, bias toward it.
2. Is another candidate clearly stronger than the expected one?
   If yes, allow disagreement.
3. Otherwise, confirm the expectation.

Operational meaning:

- good for “I think this is X, but correct me if I’m wrong”
- usually faster and more stable than pure open-ended recognition

## Confirmation

`confirmation` is the strongest expected-card check.

Use it when the parent wants a direct answer to:

- does this image match the expected card or printing?

Pipeline:

1. Run the shared recognition path in an expected-card-aware context.
2. Score the expected card directly against the observed evidence.
3. Return confirmation confidence plus contradiction detail.

Decision shape:

1. Does the observed evidence strongly support the expected card?
   If yes, return a strong confirmation.
2. Does the observed evidence materially support a different card?
   If yes, return a contradiction-oriented result.

Operational meaning:

- best for yes/no verification inside a parent workflow
- narrower than `reevaluation`

## Visual-First Small-Pool Variant

There is also a visual-first constrained path used in some session workflows.

When enabled, it tries to use already-observed art fingerprints from the
tracked pool before falling back to the normal constrained OCR path.

Decision shape:

1. Is there a strong and distinctive visual match inside the tracked pool?
   If yes, stop early.
2. Otherwise, fall back to the normal `small_pool` OCR-driven path.

This is meant to fit repeated pile-sorting use better than exact-image OCR
reuse, because the parent will usually provide new photos rather than the same
image bytes again.

## Current Fallback Rules

The slow fallback path is intentionally narrower than it used to be.

Today, the engine tries to avoid broad second-pass work by:

- skipping the slow fallback when the first result is already decisive enough
- reranking inside the already plausible candidate set instead of reopening the
  whole catalog
- using a split-specific rotated whole-card OCR fallback before the generic
  support ROIs only when split-title strips are weak enough to justify it
- stopping after the first useful support ROI rather than always reading every
  extra ROI

That is why mean runtime alone is not enough to judge a change. A fallback
policy can look fine on average while still producing terrible outliers.

## Why Variance Matters

For live usage, especially on Raspberry Pi 5 hardware, the important question
is often:

- is the mode consistently okay?

not just:

- what is the average runtime?

That is why the benchmark summaries now report:

- mean
- median
- standard deviation
- p95
- max

Interpretation:

- a high mean with a low median usually means a few awful outliers
- a higher but tight median/p95 means a mode is broadly slow, not spiky

## Granular Timing Study

Yes, a more granular timing study makes sense.

The next useful level would not be “time every line of code.” It would be:

- title OCR time by ROI label
- title OCR time by rotation angle
- title OCR time by layout family
- candidate-matching time by candidate count
- fallback frequency by set, layout family, and mode
- visual tie-break usage rate by mode

For split and planar-style titles specifically, useful next timing slices are:

- `90` versus `270` rotation
- whole-card rotated OCR versus narrow strip OCR
- matched-box location clusters by set family

That would let the project answer questions like:

- which families really need whole-card rotated search?
- which families can use a much tighter ROI safely?
- which modes are slow because of OCR versus candidate ambiguity?

## Recommended Next Documentation

If parent repos start relying on these operational modes more heavily, the next
docs worth adding would be:

- a compact result-schema reference for each mode
- a parent-workflow cookbook for common sorter tasks
- a layout-family note for split, planar, room, and nonstandard titles
