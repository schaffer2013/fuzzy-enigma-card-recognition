from card_engine.config import EngineConfig
from card_engine.adapters.sortingmachine import SortingMachineRecognizer
from card_engine.models import Candidate, RecognitionResult
from card_engine.operational_modes import CandidatePool, ExpectedCard


class DummyImage:
    shape = (10, 5, 3)


def test_adapter_returns_minimal_contract():
    recognizer = SortingMachineRecognizer()
    output = recognizer.recognize_top_card(DummyImage())
    assert output.card_name is None
    assert output.confidence == 0.0


def test_adapter_passes_config_through_to_engine(monkeypatch):
    seen = {}

    class FakeSession:
        def __init__(self, *, config=None, auto_track_results=False):
            seen["config"] = config
            seen["auto_track_results"] = auto_track_results

        def recognize(self, frame, **kwargs):
            seen["frame"] = frame
            seen["kwargs"] = kwargs
            return type("Result", (), {"best_name": "Opt", "confidence": 0.9})()

        def add_expected_card(self, expected_card):
            seen["expected_card"] = expected_card
            return True

        def get_tracked_pool_entries(self):
            return ["tracked-entry"]

        def clear_tracked_pool(self):
            seen["cleared"] = True

    monkeypatch.setattr("card_engine.adapters.sortingmachine.RecognitionSession", FakeSession)

    config = EngineConfig(candidate_count=7)
    recognizer = SortingMachineRecognizer(config=config, auto_track_results=True)
    output = recognizer.recognize_top_card(
        DummyImage(),
        mode="small_pool",
        expected_card=ExpectedCard(name="Opt", set_code="XLN", collector_number="65"),
        candidate_pool=CandidatePool.from_records([]),
        use_tracked_pool=True,
        artifact_export_dir="tmp/artifacts",
        track_result=False,
    )

    assert output.card_name == "Opt"
    assert output.confidence == 0.9
    assert isinstance(seen["frame"], DummyImage)
    assert seen["config"] is config
    assert seen["auto_track_results"] is True
    assert seen["kwargs"]["mode"] == "small_pool"
    assert seen["kwargs"]["candidate_pool"] is not None
    assert seen["kwargs"]["use_tracked_pool"] is True
    assert seen["kwargs"]["artifact_export_dir"] == "tmp/artifacts"
    assert seen["kwargs"]["track_result"] is False

    assert recognizer.add_expected_card(ExpectedCard(name="Island")) is True
    assert recognizer.get_tracked_pool_entries() == ["tracked-entry"]
    recognizer.clear_tracked_pool()
    assert seen["cleared"] is True


def test_adapter_defaults_to_stateless_default_mode(monkeypatch):
    seen = {}

    class FakeSession:
        def __init__(self, *, config=None, auto_track_results=False):
            pass

        def recognize(self, frame, **kwargs):
            seen["kwargs"] = kwargs
            return type("Result", (), {"best_name": "Opt", "confidence": 0.9})()

    monkeypatch.setattr("card_engine.adapters.sortingmachine.RecognitionSession", FakeSession)

    recognizer = SortingMachineRecognizer()
    output = recognizer.recognize_top_card(DummyImage())

    assert output.card_name == "Opt"
    assert output.confidence == 0.9
    assert seen["kwargs"]["mode"] is None
    assert seen["kwargs"]["expected_card"] is None
    assert seen["kwargs"]["use_tracked_pool"] is None
    assert seen["kwargs"]["track_result"] is None


def test_adapter_can_return_detailed_output(monkeypatch):
    class FakeSession:
        def __init__(self, *, config=None, auto_track_results=False):
            pass

        def recognize(self, frame, **kwargs):
            return RecognitionResult(
                bbox=(1, 2, 3, 4),
                best_name="Opt",
                confidence=0.9,
                ocr_lines=["Opt"],
                top_k_candidates=[
                    Candidate(
                        name="Opt",
                        score=0.9,
                        scryfall_id="opt-1",
                        oracle_id="oracle-opt",
                        set_code="XLN",
                        collector_number="65",
                        notes=["title_match"],
                    )
                ],
                active_roi="standard",
                tried_rois=["standard", "split_left"],
                debug={"mode": {"effective": "greenfield"}},
            )

    monkeypatch.setattr("card_engine.adapters.sortingmachine.RecognitionSession", FakeSession)

    recognizer = SortingMachineRecognizer()
    output = recognizer.recognize_top_card(DummyImage(), detailed=True)

    assert output.card_name == "Opt"
    assert output.confidence == 0.9
    assert output.scryfall_id == "opt-1"
    assert output.oracle_id == "oracle-opt"
    assert output.bbox == (1, 2, 3, 4)
    assert output.ocr_lines == ["Opt"]
    assert output.active_roi == "standard"
    assert output.tried_rois == ["standard", "split_left"]
    assert output.top_k_candidates[0].name == "Opt"
    assert output.top_k_candidates[0].scryfall_id == "opt-1"
    assert output.top_k_candidates[0].oracle_id == "oracle-opt"
    assert output.debug["mode"]["effective"] == "greenfield"
    assert output.raw_result.best_name == "Opt"
    assert output.requested_mode is None
    assert output.effective_mode is None
    assert output.mode_flags == {}
