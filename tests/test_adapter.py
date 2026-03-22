from card_engine.config import EngineConfig
from card_engine.adapters.sortingmachine import SortingMachineRecognizer


class DummyImage:
    shape = (10, 5, 3)


def test_adapter_returns_minimal_contract():
    recognizer = SortingMachineRecognizer()
    output = recognizer.recognize_top_card(DummyImage())
    assert output.card_name is None
    assert output.confidence == 0.0


def test_adapter_passes_config_through_to_engine(monkeypatch):
    seen = {}

    def fake_recognize_card(frame, *, config=None):
        seen["frame"] = frame
        seen["config"] = config
        return type("Result", (), {"best_name": "Opt", "confidence": 0.9})()

    monkeypatch.setattr("card_engine.adapters.sortingmachine.recognize_card", fake_recognize_card)

    config = EngineConfig(candidate_count=7)
    recognizer = SortingMachineRecognizer(config=config)
    output = recognizer.recognize_top_card(DummyImage())

    assert output.card_name == "Opt"
    assert output.confidence == 0.9
    assert isinstance(seen["frame"], DummyImage)
    assert seen["config"] is config
