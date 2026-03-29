#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_PATH="${VENV_PATH:-.venv}"
EXTRAS="${EXTRAS:-ocr,ui,moss,dev}"
UPDATE=0
SKIP_SUBMODULES=0
SKIP_CATALOG=0
PREHASH_ART=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --venv)
      VENV_PATH="$2"
      shift 2
      ;;
    --extras)
      EXTRAS="$2"
      shift 2
      ;;
    --update)
      UPDATE=1
      shift
      ;;
    --skip-submodules)
      SKIP_SUBMODULES=1
      shift
      ;;
    --skip-catalog)
      SKIP_CATALOG=1
      shift
      ;;
    --prehash-art)
      PREHASH_ART=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ "$SKIP_SUBMODULES" -eq 0 ]]; then
  if command -v git >/dev/null 2>&1; then
    echo "Syncing git submodules..."
    git submodule sync --recursive
    git submodule update --init --recursive
  else
    echo "git not found; skipping submodule sync." >&2
  fi
fi

if [[ ! -d "$VENV_PATH" ]]; then
  echo "Creating virtual environment at $VENV_PATH..."
  "$PYTHON_BIN" -m venv "$VENV_PATH"
elif [[ "$UPDATE" -eq 1 ]]; then
  echo "Reusing existing virtual environment at $VENV_PATH..."
fi

PYTHON_EXE="$VENV_PATH/bin/python"
if [[ ! -x "$PYTHON_EXE" ]]; then
  echo "Virtual environment python not found at $PYTHON_EXE" >&2
  exit 1
fi

echo "Upgrading packaging tools..."
"$PYTHON_EXE" -m pip install --upgrade pip setuptools wheel

EDITABLE_TARGET="."
if [[ -n "$EXTRAS" ]]; then
  EDITABLE_TARGET=".[${EXTRAS}]"
fi

echo "Installing editable package $EDITABLE_TARGET..."
"$PYTHON_EXE" -m pip install -e "$EDITABLE_TARGET"

if [[ "$SKIP_CATALOG" -eq 0 ]]; then
  CATALOG_DB="$REPO_ROOT/data/catalog/cards.sqlite3"
  CATALOG_JSON="$REPO_ROOT/data/catalog/default-cards.json"
  if [[ "$UPDATE" -eq 1 || ! -f "$CATALOG_DB" || ! -f "$CATALOG_JSON" ]]; then
    echo "Building local catalog..."
    "$PYTHON_EXE" scripts/build_catalog.py --download
  else
    echo "Catalog already present; skipping rebuild."
  fi
fi

if [[ "$PREHASH_ART" -eq 1 ]]; then
  echo "Prehashing missing art references..."
  "$PYTHON_EXE" scripts/prehash_missing_art_refs.py
fi

echo
echo "Environment ready."
echo "Activate with: source $VENV_PATH/bin/activate"
echo "Run tests with: $PYTHON_EXE -m pytest --engine-only"
