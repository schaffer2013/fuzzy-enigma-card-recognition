import sys
import os
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root))


def pytest_addoption(parser):
    parser.addoption(
        "--engine-only",
        action="store_true",
        help="Skip UI-only tests and collect only engine-facing tests.",
    )
    parser.addoption(
        "--ui-only",
        action="store_true",
        help="Collect only UI-only tests.",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "ui: tests for the optional debug UI layer")


def pytest_ignore_collect(collection_path, config):
    scope = os.getenv("CARD_ENGINE_TEST_SCOPE", "").strip().lower()
    path = Path(str(collection_path))
    is_ui_test = path.name.startswith("test_ui_")
    if config.getoption("--engine-only") or scope == "engine":
        return is_ui_test
    if config.getoption("--ui-only") or scope == "ui":
        return path.name.startswith("test_") and not is_ui_test
    return False
