# Fuzzy Enigma Card Recognition Roadmap

## Project Summary

Build a lightweight card recognition engine in its own repository that:

- Takes an input image.
- Finds the probable card bounding box.
- Crops and normalizes the card region.
- Performs OCR on targeted card regions.
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
   - Use a practical OCR backend on targeted regions of the normalized card.
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
- Narrow exceptions are allowed for tie-breaking: after OCR and catalog ranking have reduced the search to a small top-candidate set, the engine may compare small normalized ROIs around the set symbol area and, when needed, the art box.
- The preferred flow is to OCR the name first, then use the set-symbol ROI hash against the top name candidates before spending time on other OCR regions.
- If the set symbol is still too weak to separate same-name printings, the engine may apply an art-region fingerprint against the same near-tied candidate pool before falling back to more OCR.
- The first implementation step for visual fingerprints should be **lazy caching on first use**: compute and persist candidate-specific ROI fingerprints only when a recognition run actually needs them.
- The final implementation should be an **optional offline warm-cache step** that can prebuild visual fingerprints ahead of time, but it must never be required at normal app startup.
- Set-symbol comparison should apply to all near-tied same-name candidates, not just an arbitrary small prefix of the ranked list.
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
- **Mode-aware**: the engine should support both open-ended recognition and constrained matching flows so repeated sorter scans do not always pay full-catalog cost.
- **Explicit state**: any tracked candidate pool must be intentionally created, inspectable, and clearable instead of being hidden implicit state.

---

## Proposed Repository Structure

```text
fuzzy-enigma-card-recognition/
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

Use OCR on targeted regions, not the entire source image.

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
- Use a small art-region fingerprint as a second late-stage tie-breaker when the set-symbol ROI is not distinctive enough, especially for basics and art-driven reprints.
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
- Late-stage art-region fingerprint agreement for same-name printings with weak or ambiguous set symbols.
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

### Recognition Modes

The engine should eventually support a stateless default mode plus several
specialized operating modes. These modes have heavy implementation overlap and
should share the same detector,
normalization, ROI, OCR, and scoring primitives wherever possible. The main
difference between modes is how the candidate pool is constructed and how the
final confidence should be interpreted.

1. **Default recognition**
   - Stateless baseline behavior.
   - Similar to greenfield recognition, but without any tracked-pool
     management.
   - The scanned card may be any card in the catalog.
   - Use the full matching pipeline against the full local catalog.
   - This should remain the simplest entry point and the default API behavior.

2. **Greenfield recognition**
   - Open-ended recognition with optional tracked-pool accumulation.
   - The scanned card may be any card in the catalog.
   - Use the full matching pipeline against the full local catalog.
   - Unlike default mode, this mode may add confirmed results into a tracked
     pool that later constrained modes can reuse.
   - This is useful when building up a working set of cards during an active
     sorting session.

3. **Re-evaluation**
   - The system already has an expected card or printing and wants to verify
     whether the new scan agrees or whether the true card is something else.
   - This mode should bias the expected card heavily, surface agreement versus
     disagreement signals explicitly, and still be able to recover to the true
     card if the expectation is wrong.
   - This is useful for rescans, audit passes, and sorter confirmation after an
     earlier tentative identification.

4. **Small-pool recognition**
   - The scanned card is known to come from a pre-confirmed pool of candidate
     cards or printings.
   - The engine should only rank candidates from that supplied pool instead of
     searching the entire catalog.
   - This mode is important for pile sorting and repeated scans where the same
     local set of cards may be seen many times and full-catalog search would be
     unnecessary overhead.

5. **Confirmation / expected-printing scoring**
   - The caller already knows the expected printed card and wants a confidence
     score that the photo matches that exact printing.
   - This mode should return a confirmation score plus the strongest supporting
     and contradicting signals, rather than primarily acting like an open-ended
     search.
   - This is the narrowest and cheapest mode when the task is strict
     photo-versus-printing verification.

### Tracked Pool Lifecycle

Pool-backed workflows need explicit state management.

- There should be a tracked pool abstraction representing the cards or
  printings that are currently in scope for a sorting session.
- Greenfield and re-evaluation flows may add confirmed results into that pool
  when the caller opts into session-based tracking.
- Small-pool mode may consume either a caller-supplied pool or the current
  tracked pool.
- The system should expose a way to inspect the current tracked pool.
- The system should expose a way to clear or reset the tracked pool at any
  time.
- Default recognition should not implicitly create or mutate a tracked pool.

These modes do not need separate pipelines. A practical design
is to keep one shared recognition core and expose:

- a stateless full-catalog entry point for default mode
- a full-catalog candidate generator with optional pool updates for greenfield mode
- a constrained candidate generator for small-pool mode
- an expectation-aware reranker for re-evaluation mode
- a direct comparison / confirmation wrapper for expected-printing mode

### Core Engine API

Target API shape:

```python
result = recognize_card(image)
```

Future mode-aware API shape could look more like:

```python
result = recognize_card(image)
result = recognize_card(image, mode="greenfield")
result = recognize_card(image, mode="small_pool", candidate_pool=pool)
result = recognize_card(image, mode="recheck", expected_card=expected)
result = confirm_printing(image, expected_card=expected)

session_pool = recognizer.get_tracked_pool()
recognizer.clear_tracked_pool()
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
- Do not block normal startup on precomputing visual fingerprint caches for the whole catalog.

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

- `third_party/fuzzy-enigma-card-recognition`
- `external/fuzzy-enigma-card-recognition`

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
- Recognition mode.
- Optional expected card / printing.
- Optional constrained candidate pool.
- Optional tracked-pool persistence policy.
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
- [x] Milestone 5 is complete.
- [x] Milestone 6 is complete.
- [ ] Milestone 7 is partially complete.
- [ ] Milestone 8 is partially complete.
- [x] Milestone 9 is complete.
- [x] Milestone 10 is complete.
- [x] Milestone 11 is complete.
- [x] Milestone 12 is complete.
- [x] Milestone 13 is complete.

Recommended next step:

- Treat the broad split-family hardening pass as mostly complete and focus the
  next split work on long-tail promotional/nonstandard printings plus latency
  cleanup, rather than on baseline family correctness.

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
10. Operational recognition modes.

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

- [x] OCR backend integration.
- [x] Title-region OCR.
- [x] Alternate-ROI OCR.
- [x] OCR result normalization.
- [x] Debug overlays for OCR regions.

**Deliverables**

- OCR backend integration.
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
- [x] Adapter passes injected config through to the underlying recognition API.
- [ ] Minimal integration docs.
- [ ] Example configuration.
- [x] Smoke test against parent-style frames.

**Deliverables**

- Adapter compatible with SortingMachineArray.
- Adapter honors caller-supplied engine configuration.
- Minimal integration docs.
- Example configuration.
- Smoke test against parent-style frames.

**Exit Criteria**

- Engine can be called from the parent repo through a single adapter.
- Parent projects can actually influence recognition behavior through the
  adapter's config surface.
- No parent-level architectural changes are required beyond wiring.

### Milestone 9: Accuracy and Hardening

**Status**

- [x] Fixture-based evaluation tool.
- [x] Confidence calibration tuning and validation on larger unseen samples.
- [x] Better tie-breaking from non-collector OCR regions.
- [x] Set-symbol ROI hash tie-breaker for near-equal top candidates.
- [x] Art-region fingerprint tie-breaker for same-name printings when set symbols are weak.
- [x] Fast-path skip of secondary OCR when title plus set-symbol evidence is already confident enough.
- Deferred beyond Milestone 9: fallback title OCR path for split cards and other nonstandard title placements.
- [x] Improved region cropping.
- [x] Lightweight per-stage timing in eval/debug output.
- [x] Documented extension points for image hashing in v2.
- [x] Lightweight profiling and benchmark write-up for current pipeline stages.

**Current Progress Notes**

- Fixture evaluation is in place and now supports timed random sampling plus
  name/set/art accuracy reporting.
- For the current Milestone 9 close-out, exact card-name accuracy on paper
  printings is the primary success criterion; exact-printing disambiguation is
  still useful but is treated as secondary unless it harms name-level
  recognition quality.
- Confidence-calibration reporting is in place, including confidence bins and
  expected calibration error (ECE), and the closeout validation on a fresh
  66-card paper-English random sample held `1.000` top-1 name accuracy with
  `0.021` ECE, which did not justify a confidence-threshold rebalance.
- Same-name printing tie-breaking is materially improved through set-symbol and
  art-region visual comparisons plus a fast path that skips secondary OCR when
  title and visual evidence are already strong.
- Repo-committed ROI tuning now serves as the source of truth for region
  cropping, and that closeout pass is sufficient for Milestone 9's current
  name-first paper-recognition goals.
- Split cards and some nonstandard print layouts still need a dedicated
  fallback title OCR path instead of relying only on the normal title band,
  but that work is explicitly deferred beyond Milestone 9.
- Pathological long-running cases are now bounded by deadline-aware recognition,
  capped visual tie-break work, and download timeouts, and the repo now exposes
  lightweight stage-level timing visibility in both recognition debug output and
  eval summaries.
- The benchmark workflow now supports saved-summary comparisons, all-mode runs
  against the same fixture set, simulated expected-vs-actual pair tracking, and
  ETA reporting for long runs. The Milestone 9 closeout benchmark write-up now
  captures the main bottleneck explicitly: `secondary_ocr` still dominates
  runtime relative to detection and normalization.
- Hash-related ROI bounds now live in a committed repo config, and
  reference-image visual caches are invalidated automatically when those
  specific ROI bounds change.

**Deliverables**

- Fixture-based evaluation tool.
- Confidence calibration reporting, plus confidence tuning validated on larger unseen samples.
- Better tie-breaking from non-collector OCR regions.
- Set-symbol ROI hash tie-breaker for near-equal top candidates.
- Art-region fingerprint tie-breaker for same-name printings when set symbols are weak.
- Fast-path skip of secondary OCR when title plus set-symbol evidence is already confident enough.
- Improved region cropping.
- Lightweight per-stage timing in eval/debug output.
- Documented extension points for image hashing in v2.
- Lightweight profiling and benchmark write-up for current pipeline stages.

**Visual Fingerprint Rollout**

1. First step:
   Use lazy on-demand caching for set-symbol and art-region fingerprints. When a recognition run needs a candidate-specific visual comparison, compute that fingerprint then persist it to a separate cache for reuse.
2. Final implementation:
   Add an optional offline warm-cache script that can precompute visual fingerprints from the local catalog or from frequently seen eval candidates. This should be a maintenance action, not a startup requirement.

**Exit Criteria**

- Measurable improvement over MVP.
- Reproducible eval workflow exists.
- Common failure modes are documented.
- Confidence is calibrated against larger unseen samples rather than only
  reported.
- Same-name printings with distinct set symbols can be separated when OCR text alone is insufficient.
- Same-name printings with weak or ambiguous set symbols can still be separated using a small art-region fingerprint when that signal is more distinctive.
- Secondary OCR passes can be skipped on a meaningful subset of fixtures without hurting baseline accuracy.
- Recognition runtime is bounded on pathological same-name pools, and those
  bounds are reflected in lightweight timing output plus benchmark notes.
- v2 path for visual fingerprinting is defined without affecting v1 simplicity.
- Split-card title fallback is tracked as future expansion rather than a
  blocker for Milestone 9 closeout.

### Milestone 10: Operational Recognition Modes

**Status**

- [x] Default stateless mode formalized as the baseline API behavior.
- [x] Greenfield mode formalized as the baseline API behavior.
- [x] Re-evaluation mode.
- [x] Small-pool recognition mode.
- [x] Confirmation / expected-printing scoring mode.
- [x] Tracked pool abstraction and lifecycle management.
- [x] Clear/reset tracked-pool action.
- [x] Shared mode-aware candidate generation interfaces.
- [x] Adapter hooks for supplying expected cards or constrained pools.
- [x] Benchmarks comparing full-catalog versus constrained-pool runs.
- [x] Tests covering mode-specific confidence semantics.

**Current Progress Notes**

- `recognize_card(...)` now accepts an explicit `mode`, plus `candidate_pool`
  and `expected_card` inputs for mode-aware routing.
- `default` and `greenfield` are formalized as explicit API modes.
- `small_pool` is now a first-class constrained mode in the API rather than
  only an evaluation helper.
- A `RecognitionSession` abstraction now owns a tracked pool with inspect,
  add, and clear operations, so session-backed workflows no longer need to
  manage pool state ad hoc in the caller.
- `reevaluation` now biases the expected card while still allowing
  disagreement recovery when the observed evidence is materially stronger.
- `confirmation` now reports expected-printing confidence directly and surfaces
  the strongest contradicting candidate in debug output.
- The sorter adapter now exposes tracked-pool/session hooks without requiring
  any UI-specific integration.

**Deliverables**

- A stateless default recognition entry point.
- A mode-aware recognition entry point.
- A tracked pool abstraction with inspect and clear operations.
- Shared candidate-pool abstractions.
- Re-evaluation flow that can both verify and overturn a bad expectation.
- Small-pool flow that only ranks within a supplied pool.
- Confirmation flow that returns a confidence score for a specific expected printing.
- Adapter-level support for sorter workflows that repeatedly scan known piles.
- Benchmarks showing the runtime benefit of constrained modes.

**Exit Criteria**

- Callers can choose between open-ended recognition and constrained matching
  without maintaining separate pipelines.
- Default recognition remains simple and does not require pool state.
- Repeated scans against a known pile no longer require full-catalog search.
- Re-evaluation and confirmation flows expose confidence in a way that is
  useful for sorter decisions and audit passes.
- Tracked pool state can be inspected and cleared deterministically by the
  caller.
- Mode-specific behavior is documented and covered by automated tests.

### Milestone 11: Pipeline Benchmarking and Performance Engineering

**Status**

- [x] Persistent benchmark harness beyond ad hoc eval/debug timing.
- [x] Benchmark harness for repeated runs against representative fixture sets.
- [x] Version-to-version benchmark reporting for pipeline changes.
- [x] Baseline latency and throughput targets for common workflows.
- [x] Hotspot analysis for OCR, visual tie-breaks, catalog lookup, and image preprocessing.
- [x] Investigation of multithreading opportunities.
- [x] Investigation of GPU-accelerated paths where available.
- [x] Optimization backlog prioritized by measured impact.

**Deliverables**

- A repeatable benchmark workflow that records end-to-end recognition time
  beyond the lightweight instrumentation already added for hardening.
- Durable benchmark reports for major pipeline phases such as detection,
  normalization, OCR, matching, set-symbol comparison, art comparison, and
  final scoring.
- Benchmark reports that can compare different versions of the pipeline on the
  same fixture sets.
- Baseline measurements for single-image recognition, repeated-pile scanning,
  and constrained-pool recognition once those modes exist.
- A documented list of candidate optimizations, including CPU parallelism,
  caching, multithreading, and GPU acceleration where justified.

**Exit Criteria**

- Developers can measure how long recognition takes end to end and by stage.
- Pipeline changes can be compared against prior versions using the same
  benchmark workflow.
- The slowest stages are identified from measured data rather than intuition.
- The roadmap contains a prioritized speedup plan informed by benchmark
  results.
- At least one measured optimization pass has reduced real benchmark latency on
  representative fixtures.

**Current Progress Notes**

- A mode-aware operational baseline now exists in
  `docs/milestone11-baseline.md` and
  `data/sample_outputs/m11-operational-baseline.json`.
- On the current 66-card paper-English fixture set:
  - `greenfield` baseline averages `3.824s`
  - `reevaluation` baseline averages `3.382s`
  - `small_pool` averages `1.181s`
  - `confirmation` averages `1.216s`
- The dominant open-ended bottleneck is still `secondary_ocr`.
- The dominant constrained-mode bottleneck is `title_ocr`.
- Visual tie-break stages are already cheap relative to OCR and should not be
  the first optimization target.
- The first measured optimization pass reduced average runtime on the same
  fixture set to `2.678s` for `greenfield` and `2.423s` for `reevaluation`
  without changing top-1 accuracy.
- Variance-aware reporting is now part of the benchmark workflow, so the repo
  tracks median, p95, max, and runtime standard deviation in addition to the
  mean.
- On the current 20-card operational benchmark, `small_pool` and
  `confirmation` are already in a tight latency band, while `greenfield` and
  `reevaluation` are mainly hurt by tail-latency outliers rather than broad
  baseline slowness.
- The current tail-tuning pass reduced open-ended worst-case latency
  materially on that benchmark slice by restricting secondary reranking to the
  already plausible candidate set and allowing secondary OCR to stop after the
  first useful support ROI.
- For the expected Raspberry Pi 5 deployment target, multithreading is worth
  keeping for background/batch work such as prehashing, but it is not yet the
  right default for live single-card recognition.
- GPU acceleration remains a future research path rather than a Milestone 11
  requirement, because the current Pi-oriented bottleneck is OCR policy and
  fallback behavior, not an obviously GPU-shaped preprocessing stage.

### Milestone 12: Offline Catalog Query Layer

**Status**

- [x] Direct query helpers for `oracle_cards`.
- [x] Direct query helpers for `printed_cards`.
- [x] Parent-facing guidance on when to use `oracle_id` versus `scryfall_id`.
- [x] Decide which offline catalog fields should flow into parent-facing query
  and adapter surfaces.
- [x] Lightweight offline inspection/query script for parent-side debugging.
- [x] Keep catalog/query scope focused on non-digital paper printings.
- [x] Investigate a custom OCR path by fine-tuning PaddleOCR on Magic-specific
  title crops, with optional ONNX/RapidOCR deployment if the training results
  justify the added maintenance.

**Deliverables**

- Query helpers that can address Oracle-level identity and exact-printing
  identity separately without relying only on the compatibility view.
- A documented mapping between `oracle_cards` and `printed_cards`.
- Parent-facing guidance for exact-printing lookups versus grouped same-card
  queries.
- A small offline inspection/query entry point for local debugging and parent
  integration work.
- A decision memo on whether a custom-trained OCR recognizer is worth
  maintaining relative to ROI tuning and fallback-policy improvements.

**Exit Criteria**

- Parent applications can query exact printings and grouped Oracle identities
  fully offline.
- The normalized catalog shape is exposed intentionally rather than only as an
  internal storage detail.
- Parent-facing APIs and docs clearly explain which identifiers and fields are
  stable integration points.
- The offline query surface remains scoped to paper-relevant cards and
  printings.
- The roadmap explicitly captures whether custom OCR training remains a future
  investment path or should be deferred in favor of cheaper OCR/ROI
  heuristics.

**Current Progress Notes**

- `card_engine.catalog.query.OfflineCatalogQuery` now exposes direct Oracle and
  printed-card queries against the normalized offline SQLite catalog.
- `scripts/query_offline_catalog.py` provides a lightweight parent-side
  inspection entry point for Oracle-level and exact-printing lookups.
- Parent-facing docs now explain when to use `oracle_id` versus `scryfall_id`.
- The offline query layer stays scoped to the paper-only catalog build.
- A short decision note in `docs/custom-ocr-decision.md` records the current
  choice to defer custom OCR training until cheaper OCR/ROI improvements are
  exhausted.

### Milestone 13: UI / Engine Package Decoupling

**Status**

- [x] Separate engine-facing and UI-facing dependency groups cleanly.
- [x] Ensure parent repos can install and test engine-only code without UI
  dependencies.
- [x] Move UI-only test coverage behind a UI-specific test target.
- [x] Keep adapter and integration examples free of UI imports.
- [x] Make package/module boundaries explicit in docs and CI/local commands.

**Deliverables**

- A packaging boundary where the recognition engine, adapter, catalog, and
  benchmark workflows can be installed without pulling in UI code.
- UI-specific entry points, dependencies, and tests that are optional for
  parent repos embedding this project as a submodule.
- A documented test matrix that distinguishes engine-only validation from
  UI/debug validation.
- CI or local test commands that let parent repos avoid irrelevant UI test
  runs.

**Exit Criteria**

- Parent repos can depend on the engine package without importing or testing
  the debug UI layer.
- Engine-only test runs do not require UI libraries or UI fixtures.
- The UI remains available for local debugging, but it is clearly optional and
  isolated from the integration surface.
- README/integration docs explain the package split and the intended install
  paths for submodule consumers.

**Current Progress Notes**

- Engine-only tests can now run with `python -m pytest --engine-only`, which
  skips UI-only test modules at collection time.
- UI-only tests can run with `python -m pytest --ui-only`.
- Core API tests no longer import the debug UI module just to construct
  editable image fixtures.
- Install and test docs now distinguish engine-only and UI/debug workflows for
  parent repos.
- If the repo ever needs a harder packaging boundary, the next step would be a
  true `core` / `ui` distribution split, with the UI package depending on the
  engine package rather than parent repos depending on the UI layer directly.

### Milestone 14: Release And Operationalization

**Status**

- [ ] Versioning policy and first tagged release.
- [ ] Changelog and release checklist.
- [ ] Minimal CI matrix for engine-only and full-suite validation.
- [ ] Clean-install smoke test from a parent-repo workflow.
- [ ] Supported-platform guidance, especially for Raspberry Pi 5.

**Deliverables**

- A documented release process that can produce a stable first public release.
- A lightweight changelog or release-notes flow.
- Automated validation that distinguishes engine-only usage from full local
  development coverage.
- A clean-room smoke test showing that a parent repo can install and call the
  engine without relying on local dev state.
- A short supported-platform note for the intended Pi-oriented deployment
  target.

**Exit Criteria**

- The project can produce a repeatable tagged release with a documented
  validation checklist.
- Engine-only consumers have a clear install-and-test story.
- Basic publish/install regressions are caught before release.

### Milestone 15: Long-Tail Recognition Cleanup

**Status**

- [ ] Long-tail promotional and nonstandard split printings.
- [ ] Benchmark filtering or separate labeling for tokens, emblems, and other
  out-of-scope objects.
- [ ] Remaining pathological slow-card cases.
- [ ] Clearer documentation of low-confidence or out-of-scope object classes.

**Deliverables**

- A tracked set of long-tail recognition fixtures that are outside the main
  family-level split/layout fixes.
- Cleaner benchmark interpretation for paper-card recognition by separating
  or excluding out-of-scope objects.
- Follow-up runtime improvements on the slowest remaining live-recognition
  outliers.
- Explicit docs for what the engine currently treats as supported,
  unsupported, or best-effort.

**Exit Criteria**

- Benchmarks are no longer meaningfully distorted by obviously out-of-scope
  objects.
- Remaining split/layout work is reduced to isolated edge cases rather than
  recurring family-level regressions.
- The project has a clearer public statement of current recognition limits.

### Milestone 16: Packaging Split Decision

**Status**

- [ ] Decide whether the current dependency/test boundary is sufficient long
  term.
- [ ] If needed, design a real `core` / `ui` package split.
- [ ] Document the migration path for parent repos if that harder split is
  ever adopted.

**Deliverables**

- A decision note on whether to keep the current single-package structure.
- If needed, a concrete package layout for a true engine/UI distribution
  split.
- A compatibility/migration note for existing parent repos.

**Exit Criteria**

- The project has an explicit packaging direction instead of an implied one.
- Parent repos know whether they should expect a future package-boundary
  change.

### Milestone 17: Parent Workflow Polish

**Status**

- [ ] Higher-level result states for parent workflows.
- [ ] Clearer low-confidence, timeout, and out-of-scope semantics.
- [ ] Parent-facing guidance for how to react to ambiguous or over-budget
  scans.

**Deliverables**

- A clearer parent-facing result vocabulary such as recognized, ambiguous,
  over-budget, and out-of-scope.
- Parent-integration guidance for handling low-confidence and failure cases
  consistently.
- Any needed adapter/API tweaks that make sorter behavior easier to reason
  about.

**Exit Criteria**

- Parent repos can make better workflow decisions without reading deep engine
  debug payloads.
- Timeout and ambiguity behavior are easier to consume operationally.

## Operational Quality Gates

- Live recognition should not treat results over `20s` as success cases.
- Benchmarks should track median, p95, max, and variance in addition to the
  mean.
- Engine-only install and test workflows should remain clean for submodule
  consumers.

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
- Set accuracy.
- Art/printing accuracy.
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
  - **Mitigation:** Add a small normalized set-symbol ROI hash first, then an art-region fingerprint for stubborn same-name ties where the symbol is not distinctive enough.
- **Risk:** Confidence is poorly calibrated.
  - **Mitigation:** Build a fixture-based evaluation loop and tune thresholds from actual results.

---

## Open Questions

These can remain unresolved initially, but should be tracked:

- Which atypical layouts need first-class ROI presets earliest?
- Which non-collector OCR regions are most reliable for tie-breaking?
- Should type-line OCR be part of MVP or immediately after MVP?
- How should layout classification interact with ROI cycling?
- Would a Magic-specific PaddleOCR fine-tune materially outperform ROI tuning
  and fallback-policy work enough to justify dataset curation, training, and
  long-term model maintenance?
