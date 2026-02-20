from __future__ import annotations

from PySide6 import QtWidgets

from momentum_companion.bootstrap import bootstrap
from momentum_companion.execution.emm_engine import EMMEngine
from momentum_companion.execution.trade_executor import TradeExecutor
from momentum_companion.triggers.synthetic import SyntheticTriggerEngine
from momentum_companion.clients.schwab_rest import SchwabRestClient
from momentum_companion.clients.schwab_stream import SchwabStreamClient
from momentum_companion.clients.token_provider import TokenProvider
from momentum_companion.utils.paths import instance_db_path
from momentum_companion.ui.main_window import MainWindow
from momentum_companion.ui.controller import UIController
from momentum_companion.llm.service import LLMService
from momentum_companion.llm.coach import LLMCoach
from momentum_companion.analysis.ae import AEEngine


def main(instance_id: str) -> None:
    db_path, app_state, journal = bootstrap(instance_id)
    app = QtWidgets.QApplication([])
    app.setStyleSheet(
        """
        QWidget { background-color: #000000; color: #c8d1da; }
        QLabel { color: #c8d1da; }
        QLineEdit, QComboBox, QPushButton { background-color: #111111; color: #c8d1da; border: 1px solid #333333; }
        QGroupBox { border: 1px solid #222222; margin-top: 6px; color: #c8d1da; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
        """
    )
    window = MainWindow()
    state_cb = window.set_state

    token_provider = TokenProvider(state_callback=state_cb)
    rest = SchwabRestClient(base_url="https://api.schwabapi.com/trader/v1", auth_token_provider=token_provider)
    ae_engine = AEEngine(rest, db_path)
    emm = EMMEngine(rest, journal)
    trig = SyntheticTriggerEngine(None)
    executor = TradeExecutor(rest, emm, trig, journal, state_callback=state_cb)
    llm_service = LLMService(LLMCoach(), journal=journal, state_callback=state_cb, flash_callback=None)
    controller = UIController(
        window,
        llm_service,
        rest_client=rest,
        stream_client=None,
        token_provider=token_provider,
        db_path=str(db_path),
        ae_engine=ae_engine,
    )
    # wire flash callback
    llm_service._flash_callback = controller.handle_flash  # type: ignore[attr-defined]
    window.show()
    app.exec()
