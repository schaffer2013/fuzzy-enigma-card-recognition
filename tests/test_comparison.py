from pathlib import Path

from card_engine.comparison import compare_recognition_pipelines
from card_engine.adapters.mossmachine import (
    MossMachineRunResult,
    MossMachineSettings,
    _stage_file_if_missing,
    run_moss_machine_recognition,
)


class DummyImage:
    shape = (100, 80, 3)


class PathImage:
    shape = (100, 80, 3)

    def __init__(self, path: Path):
        self.path = path


def test_compare_recognition_pipelines_runs_ours_and_gracefully_skips_moss_without_path(monkeypatch):
    comparison = compare_recognition_pipelines(DummyImage())

    assert comparison.ours is not None
    assert comparison.ours.engine == "fuzzy_enigma"
    assert comparison.moss is not None
    assert comparison.moss.available is False
    assert comparison.moss.failure_code == "image_path_required"


def test_compare_recognition_pipelines_normalizes_moss_results(monkeypatch, tmp_path):
    image_path = tmp_path / "fixture.png"
    image_path.write_bytes(b"fixture")

    monkeypatch.setattr(
        "card_engine.comparison.run_moss_machine_recognition",
        lambda image_path, settings=None: MossMachineRunResult(
            available=True,
            best_name="Lightning Bolt",
            confidence=0.87,
            runtime_seconds=0.42,
            candidates=[],
            debug={"source": "stub"},
        ),
    )

    comparison = compare_recognition_pipelines(PathImage(image_path))

    assert comparison.image_path == str(image_path)
    assert comparison.moss is not None
    assert comparison.moss.available is True
    assert comparison.moss.best_name == "Lightning Bolt"
    assert comparison.moss.runtime_seconds == 0.42


def test_run_moss_machine_recognition_reports_missing_repo(tmp_path):
    image_path = tmp_path / "fixture.png"
    image_path.write_bytes(b"fixture")
    settings = MossMachineSettings(repo_path=tmp_path / "missing-repo")

    result = run_moss_machine_recognition(image_path, settings=settings)

    assert result.available is False
    assert result.failure_code == "moss_repo_missing"


def test_run_moss_machine_recognition_parses_subprocess_json(monkeypatch, tmp_path):
    image_path = tmp_path / "fixture.png"
    image_path.write_bytes(b"fixture")
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    runner_path = tmp_path / "runner.py"
    runner_path.write_text("print('stub')", encoding="utf-8")

    def fake_run(command, capture_output, text, check, timeout):
        class Completed:
            returncode = 0
            stdout = """
{
  "available": true,
  "best_name": "Opt",
  "confidence": 0.91,
  "runtime_seconds": 0.55,
  "failure_code": null,
  "candidates": [
    {
      "name": "Opt",
      "set_code": "XLN",
      "collector_number": "65",
      "confidence": 0.91,
      "distance": 4.0,
      "metadata": {
        "game": "Magic: The Gathering"
      }
    }
  ],
  "debug": {
    "source": "stub"
  },
  "notes": []
}
""".strip()
            stderr = ""

        return Completed()

    monotonic_values = iter([100.0, 100.0, 100.2, 100.2, 100.9, 100.9, 101.0, 101.0, 101.05, 101.1])

    monkeypatch.setattr("card_engine.adapters.mossmachine.subprocess.run", fake_run)
    monkeypatch.setattr("card_engine.adapters.mossmachine.time.monotonic", lambda: next(monotonic_values))

    settings = MossMachineSettings(
        repo_path=repo_path,
        runner_path=runner_path,
    )
    result = run_moss_machine_recognition(image_path, settings=settings)

    assert result.available is True
    assert result.best_name == "Opt"
    assert result.candidates[0].set_code == "XLN"
    assert result.candidates[0].distance == 4.0
    assert result.debug["source"] == "stub"
    assert result.runtime_seconds == 1.1
    assert result.debug["scanner_runtime_seconds"] == 0.55
    assert result.debug["timings"]["wall_total"] == 1.1
    assert result.debug["timings"]["scanner_runtime"] == 0.55
    assert result.debug["timings"]["subprocess_wall"] == 0.7
    assert result.debug["timings"]["prepare_assets"] == 0.2
    assert result.debug["timings"]["cleanup_assets"] == 0.1
    assert result.debug["timings"]["parse_payload"] == 0.05
    assert result.debug["timings"]["subprocess_overhead"] == 0.15
    assert result.debug["timings"]["unaccounted_vs_scanner"] == 0.55


def test_run_moss_machine_recognition_auto_stages_cached_assets(monkeypatch, tmp_path):
    image_path = tmp_path / "fixture.png"
    image_path.write_bytes(b"fixture")
    repo_path = tmp_path / "repo"
    recognition_dir = repo_path / "Current version" / "recognition_data"
    recognition_dir.mkdir(parents=True)
    runner_path = tmp_path / "runner.py"
    runner_path.write_text("print('stub')", encoding="utf-8")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cached_db = cache_dir / "unified_card_database.db"
    cached_db.write_text("db", encoding="utf-8")
    cached_phash = cache_dir / "phash_cards_1.db"
    cached_phash.write_text("phash", encoding="utf-8")

    staged_db = recognition_dir / cached_db.name
    staged_phash = recognition_dir / cached_phash.name

    def fake_run(command, capture_output, text, check, timeout):
        assert staged_db.exists()
        assert staged_phash.exists()
        assert "--db-path" in command
        assert str(staged_db) in command

        class Completed:
            returncode = 0
            stdout = """
{
  "available": true,
  "best_name": "Opt",
  "confidence": 0.91,
  "runtime_seconds": 0.55,
  "failure_code": null,
  "candidates": [],
  "debug": {
    "source": "stub"
  },
  "notes": []
}
""".strip()
            stderr = ""

        return Completed()

    monotonic_values = iter([10.0, 10.0, 10.3, 10.3, 10.8, 10.8, 10.9, 10.9, 10.95, 11.0])

    monkeypatch.setattr("card_engine.adapters.mossmachine.subprocess.run", fake_run)
    monkeypatch.setattr("card_engine.adapters.mossmachine.time.monotonic", lambda: next(monotonic_values))

    settings = MossMachineSettings(
        repo_path=repo_path,
        runner_path=runner_path,
        asset_cache_dir=cache_dir,
    )
    result = run_moss_machine_recognition(image_path, settings=settings)

    assert result.available is True
    assert "auto_staged_assets=unified_card_database.db,phash_cards_1.db" in result.notes
    assert staged_db.exists() is False
    assert staged_phash.exists() is False
    assert result.debug["staged_assets"] == [
        {"path": str(staged_db), "size_bytes": 2},
        {"path": str(staged_phash), "size_bytes": 5},
    ]


def test_stage_file_prefers_hardlink(monkeypatch, tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "runtime" / "source.db"
    source.write_text("db", encoding="utf-8")
    seen = {}

    def fake_link(link_source, link_target):
        seen["link"] = (link_source, link_target)
        link_target.write_text(link_source.read_text(encoding="utf-8"), encoding="utf-8")

    def fail_copy(*args, **kwargs):
        raise AssertionError("copy fallback should not run when hardlink succeeds")

    monkeypatch.setattr("card_engine.adapters.mossmachine.os.link", fake_link)
    monkeypatch.setattr("card_engine.adapters.mossmachine.shutil.copy2", fail_copy)

    assert _stage_file_if_missing(source, target) is True
    assert seen["link"] == (source, target)
    assert target.read_text(encoding="utf-8") == "db"


def test_stage_file_falls_back_to_copy(monkeypatch, tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "runtime" / "source.db"
    source.write_text("db", encoding="utf-8")

    def fail_link(*args, **kwargs):
        raise OSError("hardlinks unavailable")

    monkeypatch.setattr("card_engine.adapters.mossmachine.os.link", fail_link)

    assert _stage_file_if_missing(source, target) is True
    assert target.read_text(encoding="utf-8") == "db"
