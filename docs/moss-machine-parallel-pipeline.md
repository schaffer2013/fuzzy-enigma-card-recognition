# Moss Machine Parallel Pipeline

This experiment adds a side-by-side comparison lane for the external Moss Machine recognizer without changing the default `fuzzy-enigma` recognition path.

## What was added

- `third_party/moss-machine` as a git submodule pointing at the upstream repository
- `src/card_engine/adapters/mossmachine.py` for an isolated wrapper around the upstream scanner
- `src/card_engine/comparison.py` for a normalized `ours` versus `moss` comparison API
- `scripts/run_moss_machine_once.py` as a subprocess-safe bridge into the upstream scanner
- `scripts/compare_with_moss_machine.py` for manual fixture-level comparisons

## Why subprocess isolation

The upstream `optimized_scanner.py` has import-time side effects:

- it attempts package installation during import
- it prints startup logs
- it expects its own local module layout

Running it in a child process keeps those behaviors out of the main engine process and makes failures easier to report cleanly.

## Current limitations

- Moss comparisons currently require a real on-disk image path
- Moss comparisons require both `unified_card_database.db` and the game-specific `phash_cards_*.db` files
- the wrapper now auto-stages those cached assets from `data/cache/moss-machine/` into the upstream submodule when they are missing
- the wrapper still intentionally refuses to auto-download the database during comparisons
- this is an experiment lane, not a replacement for the main recognizer

## Quick start

Install the optional extras if you want the upstream scanner to import cleanly in the subprocess:

```powershell
python -m pip install -e .[moss,dev]
```

Run a single comparison:

```powershell
python scripts/compare_with_moss_machine.py data\sample_outputs\some-card.png --json
```

If your Moss assets live outside `data/cache/moss-machine/`, pass `--moss-db-path` to point at the `unified_card_database.db` file explicitly.

To hot-swap the runtime backend while keeping the parent-facing `recognize_card(...)` interface unchanged:

```powershell
$env:CARD_ENGINE_BACKEND = "moss_machine"
```

The default remains `fuzzy_enigma`. Unsupported Moss requests currently fall back to the native backend unless `recognition_backend_fallback` is disabled in `EngineConfig`.

## Next useful steps

- add fixture-batch comparison output to `src/card_engine/evaluation.py`
- record disagreement classes between the two engines
- measure how often Moss pHash candidates recover cards our OCR-first path misses
