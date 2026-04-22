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

## Performance Findings

The first parent-style benchmark on April 22, 2026 showed why Moss did not feel
as much faster as expected:

- the upstream Moss scan itself was fast on
  `data/cache/random_cards/worn-powerstone-ace686ad.png`, about `0.73-0.94s`
  when filtered to `Magic: The Gathering`
- the wrapper was adding avoidable asset-staging cost by copying
  `unified_card_database.db` (`~1.6 GB`) plus `phash_cards_1.db` (`~38 MB`)
  into the upstream runtime directory on each call, then deleting those staged
  files afterward
- each call also pays subprocess/import overhead because the upstream scanner is
  intentionally isolated

Measured on this checkout:

| Scenario | Wall Time | Notes |
| --- | ---: | --- |
| fuzzy backend, cold standalone script | `63.4s` | paid one-time catalog load and OCR warmup |
| fuzzy backend, parent-like warm second call | `7.8s` | catalog cached in process |
| Moss before hard-link staging | `3.4-5.8s` | `1.4-3.8s` spent staging DB assets |
| Moss after hard-link staging | `1.3-1.5s` | `0.73-0.75s` scan plus subprocess overhead |

The wrapper now stages Moss DB assets with filesystem hard links when possible
and falls back to copying only when hard links are unavailable. If Moss still
looks close to the native backend, inspect `debug.moss_machine.timings`:

- `scanner_runtime`: upstream Moss scan time
- `prepare_assets`: staging/linking/copying time
- `subprocess_overhead`: Python process/import overhead around the scan
- `wall_total`: total parent-visible backend runtime

## Current limitations

- Moss comparisons currently require a real on-disk image path
- Moss comparisons require both `unified_card_database.db` and the game-specific `phash_cards_*.db` files
- the wrapper auto-stages those cached assets from `data/cache/moss-machine/` into the upstream submodule when they are missing, using hard links when possible and copy fallback otherwise
- true Moss-backed mode support currently exists only for `default` and `greenfield`
- requests that depend on `reevaluation`, `small_pool`, `confirmation`, `expected_card`, or candidate-pool semantics currently fall back to the native backend unless fallback is explicitly disabled
- the wrapper still intentionally refuses to auto-download the database during comparisons
- this is an experiment lane, not a replacement for the main recognizer

## Quick start

Install the optional extras if you want the upstream scanner to import cleanly in the subprocess:

```powershell
python -m pip install -e .[moss,dev]
```

Run a single comparison:

```powershell
python scripts/compare_with_moss_machine.py `
  data\cache\random_cards\worn-powerstone-ace686ad.png `
  --moss-game "Magic: The Gathering" `
  --json
```

Use `--moss-game "Magic: The Gathering"` for parent-like Magic runs. Omitting
the game filter makes Moss search all upstream game databases, which is slower
and can make the comparison script look worse than the configured parent
backend.

If your Moss assets live outside `data/cache/moss-machine/`, pass `--moss-db-path` to point at the `unified_card_database.db` file explicitly.

To hot-swap the runtime backend while keeping the parent-facing `recognize_card(...)` interface unchanged:

```powershell
$env:CARD_ENGINE_BACKEND = "moss_machine"
```

The default remains `fuzzy_enigma`. Unsupported Moss requests currently fall back to the native backend unless `recognition_backend_fallback` is disabled in `EngineConfig`.

## Staying Current

The Moss lane is designed to stay current without bespoke manual steps:

- rerunning the repo setup script updates the editable install and nested
  submodules
- the wrapper auto-stages cached Moss DB assets from `data/cache/moss-machine/`
  into the upstream runtime layout only when needed, preferring hard links so
  large DB assets are not recopied on filesystems that support links
- updating those cached DB files is therefore enough to refresh the local Moss
  runtime data
- parent repos can advance the submodule pointer, rerun the setup script in
  update mode, and keep the same `recognize_card(...)` interface in place

## Next useful steps

- add fixture-batch comparison output to `src/card_engine/evaluation.py`
- record disagreement classes between the two engines
- measure how often Moss pHash candidates recover cards our OCR-first path misses
