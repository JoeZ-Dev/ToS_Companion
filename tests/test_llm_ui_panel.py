import pytest

qt = pytest.importorskip("PySide6")

from momentum_companion.ui.main_window import MainWindow
from momentum_companion.llm.service import LLMService
from momentum_companion.llm.coach import LLMCoach
from momentum_companion.ui.controller import UIController


class DummyCoach(LLMCoach):
    def run(self, payload, context):
        return {
            "validity": "VALID_FOR_TRADING",
            "setup_rating": "A",
            "reason_codes": [],
            "entry_price": 10.0,
            "stop_loss": 9.0,
            "target_price": 12.0,
        }

    def validate_response(self, resp):
        return True


def test_llm_panel_update(qtbot):
    window = MainWindow()
    svc = LLMService(DummyCoach())
    controller = UIController(window, svc)
    rec = DummyCoach().run({}, {})
    controller.handle_llm_output(rec)
    assert "VALID_FOR_TRADING" in window.llm_reco.text()
