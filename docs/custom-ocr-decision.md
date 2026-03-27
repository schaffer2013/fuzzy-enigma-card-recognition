# Custom OCR Decision

Date: 2026-03-26

## Question

Should this project invest in a custom-trained OCR model for Magic card title
recognition?

## Current Recommendation

Not yet.

The recommended path is to continue using the existing OCR stack and prefer
cheaper improvements first:

- better ROI/layout analysis
- better fallback policy
- family-specific handling for atypical layouts such as split cards
- benchmark-driven tuning on Raspberry Pi 5-relevant workloads

## Why

The current bottlenecks and failure modes are still dominated by:

- ROI/layout mismatch
- fallback-policy cost
- split/nonstandard title placement
- variance from a small number of hard cards

Those are all problems that a custom OCR model might help with eventually, but
they are not yet isolated enough to justify the added dataset, training,
evaluation, export, and maintenance burden.

## Future Path

If the project reaches a point where ROI and fallback policy are reasonably
stable but OCR itself still limits accuracy or latency, the next candidate path
would be:

1. collect a Magic-specific title-crop dataset
2. fine-tune PaddleOCR on that dataset
3. compare it against the current stack on the same fixture sets
4. only keep it if the measured win clearly outweighs the maintenance cost

If deployment pressure later favors the RapidOCR path, the trained recognizer
could then be exported to ONNX and evaluated there.

## Decision

Defer custom OCR training for now.
