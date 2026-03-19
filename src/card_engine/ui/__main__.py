from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    # Allow running this file directly in debuggers that execute by file path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from card_engine.ui.app import main
else:
    from .app import main


if __name__ == "__main__":
    raise SystemExit(main())
