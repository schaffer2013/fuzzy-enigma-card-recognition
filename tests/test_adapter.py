from card_engine.adapters.sortingmachine import SortingMachineRecognizer


class DummyImage:
    shape = (10, 5, 3)


def test_adapter_returns_minimal_contract():
    recognizer = SortingMachineRecognizer()
    output = recognizer.recognize_top_card(DummyImage())
    assert output.card_name is None
    assert output.confidence == 0.0
