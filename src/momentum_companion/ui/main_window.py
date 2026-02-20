from __future__ import annotations

import json
from PySide6 import QtWidgets, QtGui, QtCore

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
        ticket_group = QtWidgets.QGroupBox("Order Ticket")
        ticket_layout = QtWidgets.QFormLayout()
        ticket_layout.addRow("Side:", QtWidgets.QComboBox())
        ticket_layout.addRow("Qty:", QtWidgets.QLineEdit())
        ticket_layout.addRow("Limit Price:", QtWidgets.QLineEdit())
        ticket_group.setLayout(ticket_layout)
        chart_area.addWidget(ticket_group)
        middle.addLayout(chart_area, 3)

        side_panel = QtWidgets.QVBoxLayout()

        ae_group = QtWidgets.QGroupBox("AE Snapshot")
        ae_layout = QtWidgets.QVBoxLayout()
        self.ae_text = QtWidgets.QLabel("AE: --")
        self.ae_text.setWordWrap(True)
        self.ae_text.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        ae_layout.addWidget(self.ae_text)
        self.ae_copy_btn = QtWidgets.QPushButton("Copy Data")
        self.ae_copy_btn.setFlat(True)
        self.ae_copy_btn.setStyleSheet("text-decoration: underline; color: #2980b9;")
        self.ae_copy_btn.clicked.connect(self._copy_ae_json)
        ae_layout.addWidget(self.ae_copy_btn, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        ae_group.setLayout(ae_layout)
        side_panel.addWidget(ae_group)

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
        self._last_ae_snapshot: dict | None = None

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

    def update_ae_panel(self, snapshot: dict | None) -> None:
        """Render AE snapshot in compact sections."""
        self._last_ae_snapshot = snapshot
        if not snapshot:
            self.ae_text.setText("AE: --")
            return
        regime = snapshot.get("regime") or {}
        vol = snapshot.get("volatility") or {}
        volume = snapshot.get("volume") or {}
        levels = snapshot.get("levels") or {}
        session = snapshot.get("session") or {}
        parts = []
        parts.append(f"Status: {snapshot.get('status')} | Quality: {snapshot.get('data_quality')}")
        parts.append(f"Regime: 4hEMA={regime.get('is_above_4h_ema')} open={regime.get('is_above_open')} vwap={regime.get('is_above_vwap')} mkt_green={regime.get('is_market_green')} macd={regime.get('macd_regime')}")
        parts.append(f"Vol: range%={_fmt_pct(vol.get('intraday_range_pct'))} volatile={vol.get('is_volatile_enough')} | VolMult={_fmt_num(volume.get('volume_multiple'))}")
        nr = levels.get("nearest_resistance") or {}
        ns = levels.get("nearest_support") or {}
        parts.append(f"Nearest R: {nr.get('price')} ({nr.get('source')}) dist%={_fmt_pct(nr.get('distance_pct'))}")
        parts.append(f"Nearest S: {ns.get('price')} ({ns.get('source')}) dist%={_fmt_pct(ns.get('distance_pct'))}")
        parts.append(f"In R zone: {levels.get('in_resistance_zone')} | Next cluster dist%={_fmt_pct(levels.get('distance_to_next_cluster_pct'))}")
        parts.append(f"Session: gap%={_fmt_pct(session.get('gap_pct'))} PMH={session.get('premarket_high')} PML={session.get('premarket_low')} ORH={session.get('opening_range_high')} ORL={session.get('opening_range_low')}")
        self.ae_text.setText("\n".join(parts))

    def _copy_ae_json(self) -> None:
        if not self._last_ae_snapshot:
            return
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(json.dumps(self._last_ae_snapshot, indent=2))


def _fmt_pct(val: float | None) -> str:
    if val is None:
        return "--"
    return f"{val:.2f}"


def _fmt_num(val: float | None) -> str:
    if val is None:
        return "--"
    return f"{val:.1f}"
