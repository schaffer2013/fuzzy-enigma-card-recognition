# Card Recognition Engine Roadmap

## Project Summary

Build a lightweight card recognition engine in its own repository that:

- Takes an input image.
- Finds the probable card bounding box.
- Crops and normalizes the card region.
- Performs OCR with PaddleOCR.
- Matches OCR and structural signals against a local card catalog derived from Scryfall/Scrython data.
- Exposes a small, stable adapter that can be incorporated into `SortingMachineArray` as a git submodule.
- Includes a Pygame-based UI for debugging, inspection, and fixture review.

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

- **English-only for v1**.
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

- Full-card image hashing is **not part of v1**.
- A narrow exception is allowed for tie-breaking: after OCR and catalog ranking have reduced the search to a small top-candidate set, the engine may compare a small normalized ROI around the set symbol area.
- The preferred flow is to OCR the name first, then use the set-symbol ROI hash against the top name candidates before spending time on other OCR regions.
- If the name plus set-symbol comparison is already confident enough, the engine should skip additional OCR passes on secondary ROIs.
- This should be treated as a lightweight discriminator, not a primary recognition path.
- The architecture should leave room for broader visual fingerprinting in v2, but v1 should remain OCR-first and metadata-driven.

---

## Non-Goals

For the first version, this project will **not** aim to:

- Train a custom deep-learning detector.
- Solve all multilingual recognition cases.
- Rely on collector number as a primary recognition signal.
- Require image hashing for recognition.
- Own camera capture or sorter orchestration.
- Replace the architecture of the parent project.

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
```

---

## System Architecture

### 1. Input Layer

Accept either:

- Image path.
- PIL image / numpy array.
- File-like object if needed later.

Primary output of ingestion:

- Source image.
- Metadata.
- Debug frame ID / optional timestamps.

### 2. Detection Layer

Find the most probable card region.

Initial strategy:

- Resize for faster processing.
- Grayscale / blur.
- Edge detection.
- Contour extraction.
- Quadrilateral candidate scoring.
- Fallback rectangular candidate if no perfect quad exists.

Detection score should consider:

- Aspect ratio closeness.
- Area coverage.
- Edge strength.
- Rectangularity.
- Border consistency.

### 3. Normalization Layer

Given a candidate bbox/quad:

- Apply perspective correction.
- Rotate to canonical orientation if possible.
- Resize to a fixed target dimension.
- Optionally produce region crops for OCR.

Outputs:

- Normalized full-card image.
- Title region crop.
- Optional support-region crops.
- Layout-specific ROI sets for atypical cards.

### 4. ROI / Layout Layer

This layer is important in v1.

It should:

- Define default ROIs for normal cards.
- Define alternative ROI groups for atypical layouts.
- Allow cycling through ROI groups in a deterministic order.
- Expose the active ROI selection to the Pygame UI.
- Support trying multiple OCR passes over multiple ROI candidates.

Examples of ROI groups:

- Standard title band.
- Lower text band.
- Alternate face title region.
- Split-card panel A.
- Split-card panel B.
- Adventure-style alternate region.
- Double-faced front/back candidate regions.

The system does not need to fully classify every layout perfectly before OCR. It can instead iterate through plausible ROI presets and score the results.

### 5. OCR Layer

Use PaddleOCR on targeted regions, not the entire source image.

Primary OCR targets for v1:

- Card title band.
- Alternate title regions for atypical layouts.
- Other legible supporting text regions.
- Optional type-line region if useful.

Collector number is not a required OCR dependency in v1.

Outputs:

- Text candidates.
- OCR confidence.
- Region-level debug info.
- Per-ROI OCR results for ranking.

### 6. Matching Layer

Match OCR and structure-derived signals against a local catalog.

Matching strategy:

- Exact normalized title match.
- Fuzzy title match.
- Use title OCR to generate the first candidate set as early as possible.
- Use set-symbol ROI hashing to break near-ties among same-name or near-equal title candidates before running more expensive secondary OCR when possible.
- Use other OCR regions and card properties to narrow candidates.
- Rerank candidates based on consistency across multiple OCR regions.
- When top candidates remain tied or near-tied, optionally compare a small set-symbol ROI against candidate-specific references using a lightweight image hash.

Preferred supporting properties for v1:

- Title similarity.
- Alternate title similarity.
- Type-line compatibility if available.
- Layout compatibility.
- Set code only if reliably visible.
- General OCR confidence.
- Detection quality.

Collector number may be stored in the catalog but should not be a required discriminator in v1.

### 7. Scoring Layer

Combine signals into a final ranked result.

Possible features:

- OCR title similarity.
- Early set-symbol hash agreement after title OCR.
- Alternate ROI agreement.
- Type-line agreement.
- Layout compatibility.
- Detection quality.
- OCR confidence.
- Consistency across multiple OCR passes.
- Small-ROI set-symbol hash agreement for final tie-breaking between otherwise similar printings.

Primary output:

- `best_name`
- `confidence`
- `top_k_candidates`

### 8. Integration Adapter

A thin compatibility layer for SortingMachineArray.

The adapter should map the engine’s richer output into the minimal parent-project contract.

---

## Public API

### Core Engine API

Target API shape:

```python
result = recognize_card(image)
```

Where `result` contains:

- `bbox`
- `normalized_image`
- `ocr_lines`
- `top_k_candidates`
- `best_name`
- `confidence`
- `active_roi`
- `tried_rois`
- `debug`

Suggested model:

```python
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
```

### Parent Adapter API

Target adapter behavior:

```python
recognizer = SortingMachineRecognizer(config)
result = recognizer.recognize_top_card(frame)
```

Expected adapter output:

- `card_name`
- `confidence`

The parent repo should not need to know about OCR tokens, ROI cycling, or candidate ranking internals.

---

## Local Card Catalog Strategy

Use a local SQLite database as the source of truth.

### Why SQLite

- Lightweight.
- Portable.
- Easy to rebuild.
- Good enough for 50k-60k cards.
- Supports indexed lookups and full-text search.

### Catalog Contents

Store:

- Canonical card name.
- Normalized name.
- Printed name if needed.
- Set code.
- Collector number.
- Language.
- Layout.
- Aliases / alternate search strings.
- Optional type-line text.
- Optional OCR helper fields for atypical layouts.

Do not store full card images in the main lookup database for v1.

Do not require image hashes in v1.

### Indexing Strategy

Use:

- Ordinary indexes for exact lookups.
- An aliases table.
- An FTS index for OCR-tolerant lookup.
- Optional future extension point for visual fingerprints in v2.

### Catalog Build Flow

- Fetch/export bulk card data.
- Normalize names and aliases.
- Store English-only entries for v1.
- Preserve layout metadata needed for ROI-aware matching.
- Build SQLite database.
- Atomically replace the old database.

Runtime recognition should only read from the local catalog.

---

## Pygame UI Scope

The Pygame app is a developer/debugging tool, not the primary application.

### Required Views

- Source image.
- Detected bounding box overlay.
- Normalized crop.
- OCR text panel.
- Ranked candidate list.
- Confidence and stage timings.
- Current ROI label.
- ROI cycle preview for atypical layouts.

### Required Actions

- Next / previous image.
- Rerun recognition.
- Toggle bbox overlay.
- Toggle crop view.
- Cycle ROI presets.
- Save debug bundle.
- Mark result as correct / incorrect.
- Inspect candidate breakdown.

### UI Goals

- Make failure analysis fast.
- Make detector issues visually obvious.
- Make OCR noise visible.
- Provide a convenient fixture-review workflow.
- Make atypical card region switching explicit and testable.

---

## Integration Strategy with SortingMachineArray

### Submodule Layout

Recommended parent-repo placement:

- `third_party/card-recognition-engine`
- `external/card-recognition-engine`

### Integration Rules

The child repo owns:

- Detection.
- Normalization.
- OCR.
- ROI selection and ROI cycling.
- Candidate matching.
- Catalog building.
- Debug UI.

The parent repo owns:

- Camera capture.
- Sorter orchestration.
- Move verification.
- Simulation/hardware selection.
- Dependency injection / bootstrap wiring.

### Adapter Contract

Create a thin adapter in the child repo and import it from the parent repo.

The parent repo should only need:

- Dependency installation.
- Config wiring.
- Recognizer selection.
- Adapter invocation.

### Configuration

Support config values such as:

- Catalog path.
- OCR language/model settings.
- Debug enabled.
- Detection thresholds.
- Candidate count.
- Image resize limits.
- Enabled ROI groups.
- ROI cycling order.
- Layout heuristics toggles.

---

## Milestones

### Current Progress Snapshot

What is effectively done today:

- [x] Milestone 1 is complete.
- [x] Milestone 2 is complete.
- [x] Milestone 3 is complete.
- [x] Milestone 4 is complete.
- [ ] Milestone 5 is partially complete.
- [ ] Milestone 6 is partially complete.
- [ ] Milestone 7 is partially complete.
- [ ] Milestone 8 is partially complete.
- [ ] Milestone 9 is partially complete.

Recommended next step:

- Continue **Milestone 9: Accuracy and Hardening** by finishing the set-symbol ROI hash tie-breaker, then measuring whether the fast title-plus-symbol path lets the engine skip secondary OCR while still improving top-1 accuracy on near-tied printings.

### Implementation Sequencing Adjustment

The milestone list below still describes the full intended v1 scope, but the
practical build order should change slightly based on the current scaffold.

After the project skeleton and catalog schema are in place, the next highest
leverage step is a lightweight matching stack, even before full OCR and CV
land. That gives the repo a real searchable core, lets us test title
normalization and ranking logic in isolation, and reduces the amount of
placeholder behavior carried through the API.

Recommended early implementation order:

1. Project skeleton.
2. Catalog builder and local query helpers.
3. Matching and scoring MVP on normalized text input.
4. Detection and normalization MVP.
5. ROI system.
6. OCR MVP.
7. Debug UI.
8. Parent-project adapter.
9. Accuracy and hardening.

### Milestone 1: Project Skeleton

**Status**

- [x] Repo scaffold.
- [x] Packaging.
- [x] Config model.
- [x] Core data models.
- [x] Placeholder API.
- [x] Basic tests.
- [x] README and setup docs.

**Deliverables**

- Repo scaffold.
- Packaging.
- Config model.
- Core data models.
- Placeholder API.
- Basic tests.
- README and setup docs.

**Exit Criteria**

- Project installs cleanly.
- Test suite runs.
- Main entry points exist.

### Milestone 2: Catalog Builder

**Status**

- [x] Bulk-data ingestion script.
- [x] Name normalization utilities.
- [x] SQLite schema.
- [x] English-only local catalog build pipeline.
- [x] Exact lookup helpers.
- [x] Alias support.
- [x] Layout metadata storage.

**Deliverables**

- Bulk-data ingestion script.
- Name normalization utilities.
- SQLite schema.
- English-only local catalog build pipeline.
- Exact lookup helpers.
- Alias support.
- Layout metadata storage.

**Exit Criteria**

- Local catalog can be rebuilt from source data.
- Exact name lookup works.
- Layout metadata is queryable.
- English-only v1 dataset is clean and reproducible.

### Milestone 3: Detection and Normalization MVP

**Status**

- [x] Contour-based card detector baseline.
- [x] Bbox scoring baseline.
- [x] Perspective warp baseline.
- [x] Canonical resize baseline.
- [x] Debug image outputs baseline.

**Deliverables**

- Contour-based card detector.
- Bbox/quad scoring.
- Perspective warp.
- Canonical resize.
- Debug image outputs.

**Exit Criteria**

- Engine detects a usable card region on a curated fixture set.
- Normalized crops are visually stable.

### Milestone 4: ROI System for Standard and Atypical Layouts

**Status**

- [x] ROI abstraction.
- [x] Standard card ROI presets.
- [x] Atypical layout ROI groups.
- [x] Deterministic ROI cycling.
- [x] ROI debug overlays.
- [x] Tests for ROI ordering and extraction.

**Deliverables**

- ROI abstraction.
- Standard card ROI presets.
- Atypical layout ROI groups.
- Deterministic ROI cycling.
- ROI debug overlays.
- Tests for ROI ordering and extraction.

**Exit Criteria**

- Engine can cycle through layout-specific ROIs.
- UI can display and switch active ROIs.
- OCR can run against multiple ROI candidates consistently.

### Milestone 5: OCR MVP

**Status**

- [ ] PaddleOCR integration.
- [x] Title-region OCR.
- [x] Alternate-ROI OCR.
- [x] OCR result normalization.
- [x] Debug overlays for OCR regions.

**Deliverables**

- PaddleOCR integration.
- Title-region OCR.
- Alternate-ROI OCR.
- OCR result normalization.
- Debug overlays for OCR regions.

**Exit Criteria**

- Title extraction works on common fixtures.
- Atypical layout OCR can be tested through ROI cycling.
- OCR text can drive candidate generation.

### Milestone 6: Matching and Scoring MVP

**Status**

- [x] Exact and fuzzy title matching.
- [x] Layout-aware reranking.
- [x] Support for additional OCR properties besides collector number.
- [x] Top-k ranking.
- [x] Confidence calculation.

**Deliverables**

- Exact and fuzzy title matching.
- Layout-aware reranking.
- Support for additional OCR properties besides collector number.
- Top-k ranking.
- Confidence calculation.

**Exit Criteria**

- End-to-end recognition produces a correct top result on the baseline fixture set.
- Confidence separates likely-correct from likely-incorrect predictions.
- Collector number is not required for acceptable baseline accuracy.

### Milestone 7: Pygame Debug UI

**Status**

- [x] Image browser.
- [x] Bbox overlay view.
- [ ] Normalized crop panel.
- [x] OCR panel.
- [x] Candidate list.
- [x] Keyboard shortcuts.
- [x] ROI cycling controls.
- [ ] Save-debug action.

**Deliverables**

- Image browser.
- Bbox overlay view.
- Normalized crop panel.
- OCR panel.
- Candidate list.
- Keyboard shortcuts.
- ROI cycling controls.
- Save-debug action.

**Exit Criteria**

- Developer can inspect and debug failures quickly without writing ad hoc scripts.
- Atypical layout ROIs can be cycled and reviewed visually.

### Milestone 8: Parent-Project Adapter

**Status**

- [x] Adapter compatible with SortingMachineArray.
- [ ] Minimal integration docs.
- [ ] Example configuration.
- [x] Smoke test against parent-style frames.

**Deliverables**

- Adapter compatible with SortingMachineArray.
- Minimal integration docs.
- Example configuration.
- Smoke test against parent-style frames.

**Exit Criteria**

- Engine can be called from the parent repo through a single adapter.
- No parent-level architectural changes are required beyond wiring.

### Milestone 9: Accuracy and Hardening

**Status**

- [x] Fixture-based evaluation tool.
- [ ] Confidence calibration.
- [ ] Better tie-breaking from non-collector OCR regions.
- [ ] Set-symbol ROI hash tie-breaker for near-equal top candidates.
- [ ] Fast-path skip of secondary OCR when title plus set-symbol evidence is already confident enough.
- [ ] Improved region cropping.
- [ ] Documented extension points for image hashing in v2.
- [ ] Performance profiling.

**Deliverables**

- Fixture-based evaluation tool.
- Confidence calibration.
- Better tie-breaking from non-collector OCR regions.
- Set-symbol ROI hash tie-breaker for near-equal top candidates.
- Fast-path skip of secondary OCR when title plus set-symbol evidence is already confident enough.
- Improved region cropping.
- Documented extension points for image hashing in v2.
- Performance profiling.

**Exit Criteria**

- Measurable improvement over MVP.
- Reproducible eval workflow exists.
- Common failure modes are documented.
- Same-name printings with distinct set symbols can be separated when OCR text alone is insufficient.
- Secondary OCR passes can be skipped on a meaningful subset of fixtures without hurting baseline accuracy.
- v2 path for visual fingerprinting is defined without affecting v1 simplicity.

---

## Testing Strategy

### Unit Tests

- Name normalization.
- Alias generation.
- Exact lookup.
- Bbox scoring.
- Perspective transform helpers.
- OCR post-processing.
- Candidate reranking.
- ROI preset generation.
- ROI cycle order.

### Fixture Tests

Maintain a small curated set of images covering:

- Clean front-facing card.
- Skewed card.
- Partially off-center card.
- Moderate glare.
- Noisy background.
- Visually similar card names.
- Atypical layouts with multiple OCR-relevant regions.

### Integration Tests

- End-to-end image -> result.
- Catalog build -> query.
- Adapter output shape for parent repo.
- ROI cycle -> OCR -> rerank flow.

### Evaluation Script

Add a script to run batch evaluation against fixture folders and output:

- Top-1 accuracy.
- Top-5 accuracy.
- Average confidence.
- Common error classes.
- ROI usage statistics for atypical layouts.

---

## Performance Targets

Initial practical goals:

- Catalog lookup should be effectively instantaneous after OCR candidate generation.
- Recognition should feel interactive in the Pygame tool.
- No runtime network dependency.
- Memory usage should remain modest on a normal development machine.

Exact latency targets can be added after the first working baseline.

---

## Risks and Mitigations

- **Risk:** Detector fails on hard framing.
  - **Mitigation:** Start with a robust contour-based baseline and collect failure fixtures early.
- **Risk:** OCR noise causes false positives.
  - **Mitigation:** Use targeted region OCR, normalized text, exact first-pass matching, and reranking.
- **Risk:** Atypical card layouts are inconsistent.
  - **Mitigation:** Use explicit ROI groups and deterministic cycling rather than forcing a single region strategy.
- **Risk:** Collector number is unreadable too often.
  - **Mitigation:** Avoid making collector number a v1 dependency; rely on other OCR regions and card properties.
- **Risk:** Too much logic leaks into the parent repo.
  - **Mitigation:** Enforce the adapter boundary and keep parent integration thin.
- **Risk:** Catalog gets bloated or slow.
  - **Mitigation:** Store metadata only; avoid full images and defer image hashing to v2.
- **Risk:** Same-name printings remain tied after OCR because visible text is identical.
  - **Mitigation:** Add a small normalized set-symbol ROI hash as a late-stage tie-breaker for the top candidate set only.
- **Risk:** Confidence is poorly calibrated.
  - **Mitigation:** Build a fixture-based evaluation loop and tune thresholds from actual results.

---

## Open Questions

These can remain unresolved initially, but should be tracked:

- Which atypical layouts need first-class ROI presets earliest?
- Which non-collector OCR regions are most reliable for tie-breaking?
- Should type-line OCR be part of MVP or immediately after MVP?
- How should layout classification interact with ROI cycling?
