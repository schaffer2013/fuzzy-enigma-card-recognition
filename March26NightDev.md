# March 26 Night Dev Log

## 2026-03-26 22:15 PDT
- Confirmed working branch: `feature/split-fallback-rois`.
- Committed split-family reporting and evaluation typing fixes.
- Full split benchmark rerun on current branch is still too long/stall-prone to use as a tight inner-loop check.
- Next focus:
  1. Milestone 12 offline query layer.
  2. Milestone 13 UI/engine decoupling.
  3. Return to split-family handling with better-targeted validation.
## 2026-03-26 22:35 PDT
- Added offline query layer (`OfflineCatalogQuery`) and `query_offline_catalog.py`.
- Added engine-only/UI-only test collection switches in `tests/conftest.py`.
- Moved `EditableLoadedImage` out of the UI module so core tests no longer import `card_engine.ui.app`.
- Validation complete so far:
  - `pytest --engine-only`
  - `pytest --ui-only`
  - full `pytest`
  - direct query script smoke test
- Next: commit the M12/M13 slice, then return to split-family recognition work.
