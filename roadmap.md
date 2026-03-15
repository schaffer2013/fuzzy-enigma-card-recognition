# Card Recognition Engine Roadmap

## Project Summary

Build a lightweight card recognition engine in its own repository that:

- takes an input image
- finds the probable card bounding box
- crops and normalizes the card region
- performs OCR with PaddleOCR
- matches OCR and structural signals against a local card catalog derived from Scryfall/Scrython data
- exposes a small, stable adapter that can be incorporated into `SortingMachineArray` as a git submodule
- includes a Pygame-based UI for debugging, inspection, and fixture review

The goal is to keep the engine focused, fast, and easy to integrate without leaking heavy OCR/CV concerns into the parent project.

---

## Primary Goals

1. **Reliable card localization**
   - Detect the most probable card bounding box in a source image.
   - Support imperfect framing, moderate skew, and common lighting variation.

2. **Deterministic normalization**
   - Warp the detected card to a canonical size/orientation.
   - Produce stable crops for OCR and matching.

3. **OCR-first recognition**
   - Use PaddleOCR on targeted regions of the normalized card.
   - Extract likely card title and supporting properties.

4. **Local offline catalog**
   - Maintain a local searchable catalog of ~50k-60k unique cards.
   - Avoid runtime network calls.

5. **Simple parent-project integration**
   - Expose a thin adapter compatible with `SortingMachineArray`.
   - Support incorporation as a git submodule.

6. **Useful developer tooling**
   - Provide a Pygame UI for visualizing detection, crops, OCR output, and candidate ranking.
   - Allow atypical card layouts to be cycled through visually with their own ROIs.

---

## v1 Scope Decisions

### Language Support
- **English-only for v1**
- Catalog and matching logic should assume English card names and English OCR output.
- Multilingual printed-name support is deferred to a later version.

### Atypical Card Layouts
- Atypical layouts should be supported by allowing the system and UI to **cycle through layout-specific regions of interest**.
- This includes layouts where the most useful OCR area changes depending on the face or panel being inspected.
- v1 does not need perfect semantic understanding of every layout, but it does need a consistent mechanism for iterating through candidate ROIs.

### Collector Number
- Collector number should **not** be a core dependency in v1 because it is often difficult to read reliably.
- The system should still leave room for collector number as a future supporting signal.
- v1 should instead prioritize other OCR regions and other properties that are more legible and dependable.

### Image Hashing
- Image hashing is **not part of v1**.
- The architecture should leave room for visual fingerprinting in v2, but v1 should remain OCR-first and metadata-driven.

---

## Non-Goals

For the first version, this project will **not** aim to:

- train a custom deep-learning detector
- solve all multilingual recognition cases
- rely on collector number as a primary recognition signal
- require image hashing for recognition
- own camera capture or sorter orchestration
- replace the architecture of the parent project

This repo should be a focused recognition engine, not a second full application.

---

## Design Principles

- **Offline at runtime**: recognition should not depend on external APIs.
- **Lightweight first**: prefer classical CV and deterministic heuristics before adding heavy models.
- **Composable**: keep a small API surface so the parent repo only needs a thin adapter.
- **Inspectable**: every stage should be easy to debug in the Pygame UI.
- **Rebuildable**: local card data should be generated from a repeatable build process.
- **Layout-aware**: recognition should support multiple ROIs and ordered region cycling for atypical cards.

---

## Proposed Repository Structure

```text
card-recognition-engine/
  README.md
  roadmap.md
  pyproject.toml
  src/card_engine/
    api.py
    config.py
    detector.py
    normalize.py
    ocr.py
    matcher.py
    scorer.py
    models.py
    roi.py
    catalog/
      build_catalog.py
      scryfall_sync.py
      local_index.py
    adapters/
      sortingmachine.py
    ui/
      app.py
      state.py
      widgets.py
      views.py
    utils/
      image_io.py
      geometry.py
      text_normalize.py
  scripts/
    build_catalog.py
    eval_fixture_set.py
  tests/
    test_detector.py
    test_normalize.py
    test_ocr.py
    test_matcher.py
    test_roi.py
    test_adapter.py
  data/
    fixtures/
    sample_outputs/
System Architecture
1. Input Layer

Accept either:

image path

PIL image / numpy array

file-like object if needed later

Primary output of ingestion:

source image

metadata

debug frame ID / optional timestamps

2. Detection Layer

Find the most probable card region.

Initial strategy:

resize for faster processing

grayscale / blur

edge detection

contour extraction

quadrilateral candidate scoring

fallback rectangular candidate if no perfect quad exists

Detection score should consider:

aspect ratio closeness

area coverage

edge strength

rectangularity

border consistency

3. Normalization Layer

Given a candidate bbox/quad:

apply perspective correction

rotate to canonical orientation if possible

resize to a fixed target dimension

optionally produce region crops for OCR

Outputs:

normalized full-card image

title region crop

optional support-region crops

layout-specific ROI sets for atypical cards

4. ROI / Layout Layer

This layer is important in v1.

It should:

define default ROIs for normal cards

define alternative ROI groups for atypical layouts

allow cycling through ROI groups in a deterministic order

expose the active ROI selection to the Pygame UI

support trying multiple OCR passes over multiple ROI candidates

Examples of ROI groups:

standard title band

lower text band

alternate face title region

split-card panel A

split-card panel B

adventure-style alternate region

double-faced front/back candidate regions

The system does not need to fully classify every layout perfectly before OCR. It can instead iterate through plausible ROI presets and score the results.

5. OCR Layer

Use PaddleOCR on targeted regions, not the entire source image.

Primary OCR targets for v1:

card title band

alternate title regions for atypical layouts

other legible supporting text regions

optional type-line region if useful

Collector number is not a required OCR dependency in v1.

Outputs:

text candidates

OCR confidence

region-level debug info

per-ROI OCR results for ranking

6. Matching Layer

Match OCR and structure-derived signals against a local catalog.

Matching strategy:

exact normalized title match

fuzzy title match

use other OCR regions and card properties to narrow candidates

rerank candidates based on consistency across multiple OCR regions

Preferred supporting properties for v1:

title similarity

alternate title similarity

type-line compatibility if available

layout compatibility

set code only if reliably visible

general OCR confidence

detection quality

Collector number may be stored in the catalog but should not be a required discriminator in v1.

7. Scoring Layer

Combine signals into a final ranked result.

Possible features:

OCR title similarity

alternate ROI agreement

type-line agreement

layout compatibility

detection quality

OCR confidence

consistency across multiple OCR passes

Primary output:

best_name

confidence

top_k_candidates

8. Integration Adapter

A thin compatibility layer for SortingMachineArray.

The adapter should map the engine’s richer output into the minimal parent-project contract.

Public API
Core Engine API

Target API shape:

result = recognize_card(image)

Where result contains:

bbox

normalized_image

ocr_lines

top_k_candidates

best_name

confidence

active_roi

tried_rois

debug

Suggested model:

@dataclass
class Candidate:
    name: str
    score: float
    set_code: str | None = None
    collector_number: str | None = None
    notes: list[str] | None = None

@dataclass
class RecognitionResult:
    bbox: tuple[int, int, int, int] | None
    best_name: str | None
    confidence: float
    ocr_lines: list[str]
    top_k_candidates: list[Candidate]
    active_roi: str | None
    tried_rois: list[str]
    debug: dict
Parent Adapter API

Target adapter behavior:

recognizer = SortingMachineRecognizer(config)
result = recognizer.recognize_top_card(frame)

Expected adapter output:

card_name

confidence

The parent repo should not need to know about OCR tokens, ROI cycling, or candidate ranking internals.

Local Card Catalog Strategy

Use a local SQLite database as the source of truth.

Why SQLite

lightweight

portable

easy to rebuild

good enough for 50k-60k cards

supports indexed lookups and full-text search

Catalog Contents

Store:

canonical card name

normalized name

printed name if needed

set code

collector number

language

layout

aliases / alternate search strings

optional type-line text

optional OCR helper fields for atypical layouts

Do not store full card images in the main lookup database for v1.

Do not require image hashes in v1.

Indexing Strategy

Use:

ordinary indexes for exact lookups

an aliases table

an FTS index for OCR-tolerant lookup

optional future extension point for visual fingerprints in v2

Catalog Build Flow

fetch/export bulk card data

normalize names and aliases

store English-only entries for v1

preserve layout metadata needed for ROI-aware matching

build SQLite database

atomically replace the old database

Runtime recognition should only read from the local catalog.

Pygame UI Scope

The Pygame app is a developer/debugging tool, not the primary application.

Required Views

source image

detected bounding box overlay

normalized crop

OCR text panel

ranked candidate list

confidence and stage timings

current ROI label

ROI cycle preview for atypical layouts

Required Actions

next / previous image

rerun recognition

toggle bbox overlay

toggle crop view

cycle ROI presets

save debug bundle

mark result as correct / incorrect

inspect candidate breakdown

UI Goals

make failure analysis fast

make detector issues visually obvious

make OCR noise visible

provide a convenient fixture-review workflow

make atypical card region switching explicit and testable

Integration Strategy with SortingMachineArray
Submodule Layout

Recommended parent-repo placement:

third_party/card-recognition-engine

or

external/card-recognition-engine
Integration Rules

The child repo owns:

detection

normalization

OCR

ROI selection and ROI cycling

candidate matching

catalog building

debug UI

The parent repo owns:

camera capture

sorter orchestration

move verification

simulation/hardware selection

dependency injection / bootstrap wiring

Adapter Contract

Create a thin adapter in the child repo and import it from the parent repo.

The parent repo should only need:

dependency installation

config wiring

recognizer selection

adapter invocation

Configuration

Support config values such as:

catalog path

OCR language/model settings

debug enabled

detection thresholds

candidate count

image resize limits

enabled ROI groups

ROI cycling order

layout heuristics toggles

Milestones
Milestone 1: Project Skeleton
Deliverables

repo scaffold

packaging

config model

core data models

placeholder API

basic tests

README and setup docs

Exit Criteria

project installs cleanly

test suite runs

main entry points exist

Milestone 2: Catalog Builder
Deliverables

bulk-data ingestion script

name normalization utilities

SQLite schema

English-only local catalog build pipeline

exact lookup helpers

alias support

layout metadata storage

Exit Criteria

local catalog can be rebuilt from source data

exact name lookup works

layout metadata is queryable

English-only v1 dataset is clean and reproducible

Milestone 3: Detection and Normalization MVP
Deliverables

contour-based card detector

bbox/quad scoring

perspective warp

canonical resize

debug image outputs

Exit Criteria

engine detects a usable card region on a curated fixture set

normalized crops are visually stable

Milestone 4: ROI System for Standard and Atypical Layouts
Deliverables

ROI abstraction

standard card ROI presets

atypical layout ROI groups

deterministic ROI cycling

ROI debug overlays

tests for ROI ordering and extraction

Exit Criteria

engine can cycle through layout-specific ROIs

UI can display and switch active ROIs

OCR can run against multiple ROI candidates consistently

Milestone 5: OCR MVP
Deliverables

PaddleOCR integration

title-region OCR

alternate-ROI OCR

OCR result normalization

debug overlays for OCR regions

Exit Criteria

title extraction works on common fixtures

atypical layout OCR can be tested through ROI cycling

OCR text can drive candidate generation

Milestone 6: Matching and Scoring MVP
Deliverables

exact and fuzzy title matching

layout-aware reranking

support for additional OCR properties besides collector number

top-k ranking

confidence calculation

Exit Criteria

end-to-end recognition produces a correct top result on the baseline fixture set

confidence separates likely-correct from likely-incorrect predictions

collector number is not required for acceptable baseline accuracy

Milestone 7: Pygame Debug UI
Deliverables

image browser

bbox overlay view

normalized crop panel

OCR panel

candidate list

keyboard shortcuts

ROI cycling controls

save-debug action

Exit Criteria

developer can inspect and debug failures quickly without writing ad hoc scripts

atypical layout ROIs can be cycled and reviewed visually

Milestone 8: Parent-Project Adapter
Deliverables

adapter compatible with SortingMachineArray

minimal integration docs

example configuration

smoke test against parent-style frames

Exit Criteria

engine can be called from the parent repo through a single adapter

no parent-level architectural changes are required beyond wiring

Milestone 9: Accuracy and Hardening
Deliverables

fixture-based evaluation tool

confidence calibration

better tie-breaking from non-collector OCR regions

improved region cropping

documented extension points for image hashing in v2

performance profiling

Exit Criteria

measurable improvement over MVP

reproducible eval workflow exists

common failure modes are documented

v2 path for visual fingerprinting is defined without affecting v1 simplicity

Testing Strategy
Unit Tests

name normalization

alias generation

exact lookup

bbox scoring

perspective transform helpers

OCR post-processing

candidate reranking

ROI preset generation

ROI cycle order

Fixture Tests

Maintain a small curated set of images covering:

clean front-facing card

skewed card

partially off-center card

moderate glare

noisy background

visually similar card names

atypical layouts with multiple OCR-relevant regions

Integration Tests

end-to-end image -> result

catalog build -> query

adapter output shape for parent repo

ROI cycle -> OCR -> rerank flow

Evaluation Script

Add a script to run batch evaluation against fixture folders and output:

top-1 accuracy

top-5 accuracy

average confidence

common error classes

ROI usage statistics for atypical layouts

Performance Targets

Initial practical goals:

catalog lookup should be effectively instantaneous after OCR candidate generation

recognition should feel interactive in the Pygame tool

no runtime network dependency

memory usage should remain modest on a normal development machine

Exact latency targets can be added after the first working baseline.

Risks and Mitigations
Risk: Detector fails on hard framing

Mitigation: start with a robust contour-based baseline and collect failure fixtures early.

Risk: OCR noise causes false positives

Mitigation: use targeted region OCR, normalized text, exact first-pass matching, and reranking.

Risk: Atypical card layouts are inconsistent

Mitigation: use explicit ROI groups and deterministic cycling rather than forcing a single region strategy.

Risk: Collector number is unreadable too often

Mitigation: avoid making collector number a v1 dependency; rely on other OCR regions and card properties.

Risk: Too much logic leaks into the parent repo

Mitigation: enforce the adapter boundary and keep parent integration thin.

Risk: Catalog gets bloated or slow

Mitigation: store metadata only; avoid full images and defer image hashing to v2.

Risk: Confidence is poorly calibrated

Mitigation: build a fixture-based evaluation loop and tune thresholds from actual results.

Open Questions

These can remain unresolved initially, but should be tracked:

Which atypical layouts need first-class ROI presets earliest?

Which non-collector OCR regions are most reliable for tie-breaking?

Should type-line OCR be part of MVP or immediately after MVP?

How should layout classification interact with ROI cycling?

What confidence threshold should the parent repo use for faulting or retry behavior?

Initial Development Order

Recommended implementation order:

scaffold repo and config

build English-only local catalog and exact lookups

implement detector + normalization

implement ROI system and ROI cycling

integrate title OCR

add support-region OCR for atypical layouts

implement candidate generation and scoring

add Pygame inspection UI

create parent-project adapter

add fixture evaluation and hardening

This order gives the fastest path to a usable baseline while handling atypical layouts early.

Definition of Done for v1

v1 is complete when:

a developer can point the engine at an image and get a card prediction

the engine returns bbox, OCR output, candidates, best match, confidence, and ROI debug information

the local catalog can be rebuilt offline

the catalog is English-only for v1

atypical layouts can be inspected by cycling through layout-specific ROIs

the system does not depend on collector number for baseline recognition

the Pygame UI can inspect failures visually

the repo integrates into SortingMachineArray as a submodule through a thin adapter

no runtime network dependency is required for recognition

image hashing remains an explicit v2 extension, not a v1 requirement

v2 Considerations

These are intentionally deferred:

image hashing or visual fingerprinting

multilingual printed-name support

learned detector models

more advanced layout classification

ANN/vector search for visual matching

v1 should be structured so these can be added later without breaking the adapter interface.

Immediate Next Tasks

create repo scaffold

define core dataclasses and config

implement catalog builder with SQLite

add exact lookup and FTS lookup

implement detector MVP

implement normalization MVP

implement ROI presets and ROI cycling

wire PaddleOCR title extraction

wire support-region OCR for atypical layouts

build first end-to-end fixture test

add Pygame debug window

add SortingMachineArray adapter
