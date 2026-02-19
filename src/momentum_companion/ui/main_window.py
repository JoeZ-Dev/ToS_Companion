from __future__ import annotations

from PySide6 import QtWidgets

from momentum_companion.ui.chart_widget import LightweightChartWidget


class MainWindow(QtWidgets.QMainWindow):
    """MVP UI scaffold per specs §4.1: chart + ticket + LLM panel + status."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Momentum Trading Companion")
        self.resize(1400, 900)
        self._build_layout()

    def _build_layout(self) -> None:
        central = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout()
        central.setLayout(root)

        # Top bar
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Symbol:"))
        self.symbol_input = QtWidgets.QLineEdit()
        top.addWidget(self.symbol_input)
        self.connection_label = QtWidgets.QLabel("Connection: UNKNOWN")
        top.addWidget(self.connection_label)
        self.llm_status = QtWidgets.QLabel("LLM: OFF")
        top.addWidget(self.llm_status)
        top.addStretch()
        root.addLayout(top)

        # Middle split: chart + side panel
        middle = QtWidgets.QHBoxLayout()
        chart_area = QtWidgets.QVBoxLayout()
        self.quote_label = QtWidgets.QLabel("Quote: --")
        chart_area.addWidget(self.quote_label)
        self.chart_widget = LightweightChartWidget()
        chart_area.addWidget(self.chart_widget)
        middle.addLayout(chart_area, 3)

        side_panel = QtWidgets.QVBoxLayout()
        ticket_group = QtWidgets.QGroupBox("Order Ticket")
        ticket_layout = QtWidgets.QFormLayout()
        ticket_layout.addRow("Side:", QtWidgets.QComboBox())
        ticket_layout.addRow("Qty:", QtWidgets.QLineEdit())
        ticket_layout.addRow("Limit Price:", QtWidgets.QLineEdit())
        ticket_group.setLayout(ticket_layout)
        side_panel.addWidget(ticket_group)

        llm_group = QtWidgets.QGroupBox("LLM Panel")
        llm_layout = QtWidgets.QVBoxLayout()
        self.llm_reco = QtWidgets.QLabel("Recommendation: --")
        self.llm_flash = QtWidgets.QLabel("")
        self.llm_flash.setStyleSheet("color: red; font-weight: bold;")
        llm_layout.addWidget(self.llm_reco)
        llm_layout.addWidget(self.llm_flash)
        llm_group.setLayout(llm_layout)
        side_panel.addWidget(llm_group)

        status_group = QtWidgets.QGroupBox("Status")
        status_layout = QtWidgets.QVBoxLayout()
        self.stream_label = QtWidgets.QLabel("Stream: CONNECTED")
        self.token_label = QtWidgets.QLabel("Auth: OK")
        self.last_update_label = QtWidgets.QLabel("Last Update:")
        status_layout.addWidget(self.stream_label)
        status_layout.addWidget(self.token_label)
        status_layout.addWidget(self.last_update_label)
        status_group.setLayout(status_layout)
        side_panel.addWidget(status_group)
        middle.addLayout(side_panel, 1)

        root.addLayout(middle)

        # Controls + states
        controls = QtWidgets.QHBoxLayout()
        self.reconnect_btn = QtWidgets.QPushButton("Reconnect")
        controls.addWidget(self.reconnect_btn)
        controls.addWidget(QtWidgets.QPushButton("Cancel All"))
        controls.addWidget(QtWidgets.QPushButton("Flatten"))
        self.state_label = QtWidgets.QLabel("State: OK")
        self.state_label.setStyleSheet("color: green; font-weight: bold;")
        controls.addWidget(self.state_label)
        self.banner = QtWidgets.QLabel("")
        self.banner.setStyleSheet("color: red; font-weight: bold;")
        controls.addWidget(self.banner)
        root.addLayout(controls)

        self.setCentralWidget(central)

    def set_state(self, state: str) -> None:
        """Update state label to show AUTH_REQUIRED / STREAM_DOWN / UNKNOWN_WORKING_ORDERS / LLM_INVALID_OUTPUT."""
        self.state_label.setText(f"State: {state}")
        if state in ("AUTH_REQUIRED", "STREAM_DOWN"):
            self.state_label.setStyleSheet("color: red; font-weight: bold;")
            if state == "AUTH_REQUIRED":
                self.token_label.setText("Auth: REQUIRED")
            if state == "STREAM_DOWN":
                self.stream_label.setText("Stream: DOWN")
        elif state == "UNKNOWN_WORKING_ORDERS":
            self.state_label.setStyleSheet("color: orange; font-weight: bold;")
            self.banner.setText("Gate closed: Unknown working orders. Cancel/Flatten required.")
        elif state == "LLM_INVALID_OUTPUT":
            self.state_label.setStyleSheet("color: orange; font-weight: bold;")
        else:
            self.state_label.setStyleSheet("color: green; font-weight: bold;")
            self.banner.setText("")

    def update_quote_display(self, bid: float | None, ask: float | None, last: float | None, ts_ms: int | None) -> None:
        """Display latest L1 values above the chart."""
        parts = []
        parts.append(f"Bid: {bid:.2f}" if bid is not None else "Bid: --")
        parts.append(f"Ask: {ask:.2f}" if ask is not None else "Ask: --")
        parts.append(f"Last: {last:.2f}" if last is not None else "Last: --")
        if ts_ms:
            parts.append(f"ts: {ts_ms}")
        self.quote_label.setText(" | ".join(parts))

    def apply_llm_recommendation(self, rec: dict) -> None:
        """Render basic LLM recommendation text."""
        validity = rec.get("validity", "--")
        rating = rec.get("setup_rating", "--")
        entry = rec.get("entry_price")
        stop = rec.get("stop_loss")
        target = rec.get("target_price")
        self.llm_reco.setText(f"LLM: {validity} | Rating {rating} | Entry {entry} Stop {stop} Target {target}")

    def flash_alert(self, message: str) -> None:
        """Show flash-worthy alert."""
        self.llm_flash.setText(message)
