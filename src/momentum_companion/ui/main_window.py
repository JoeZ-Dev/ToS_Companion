from __future__ import annotations

import json
from PySide6 import QtWidgets, QtGui, QtCore
from momentum_companion.utils.logging import logging

from momentum_companion.ui.chart_widget import LightweightChartWidget


class MainWindow(QtWidgets.QMainWindow):
    """MVP UI scaffold per specs §4.1: chart + ticket + LLM panel + status."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Momentum Trading Companion")
        self.resize(1400, 900)
        self._logger = logging.getLogger(__name__)
        self._build_layout()

    def _build_layout(self) -> None:
        central = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout()
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)
        central.setLayout(root)

        # Top bar
        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        top.addWidget(QtWidgets.QLabel("Symbol:"))
        self.symbol_input = QtWidgets.QLineEdit()
        self.symbol_input.setPlaceholderText("SYM")
        self.symbol_input.setMaxLength(10)
        self.symbol_input.setValidator(QtGui.QRegularExpressionValidator(QtCore.QRegularExpression("[A-Z]{0,10}")))
        top.addWidget(self.symbol_input)
        self.connection_label = QtWidgets.QLabel("Connection: UNKNOWN")
        top.addWidget(self.connection_label)
        self.llm_status = QtWidgets.QLabel("LLM: OFF")
        top.addWidget(self.llm_status)
        top.addStretch()
        root.addLayout(top)

        # Middle split: chart + side panel
        middle = QtWidgets.QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(8)
        chart_area = QtWidgets.QVBoxLayout()
        chart_area.setContentsMargins(0, 0, 0, 0)
        chart_area.setSpacing(4)
        self.chart_widget = LightweightChartWidget()
        chart_area.addWidget(self.chart_widget)
        chart_area.setStretchFactor(self.chart_widget, 1)
        ticket_group = QtWidgets.QGroupBox("Order Ticket")
        ticket_layout = QtWidgets.QFormLayout()
        ticket_layout.setContentsMargins(6, 4, 6, 6)
        ticket_layout.addRow("Side:", QtWidgets.QComboBox())
        ticket_layout.addRow("Qty:", QtWidgets.QLineEdit())
        ticket_layout.addRow("Limit Price:", QtWidgets.QLineEdit())
        ticket_group.setLayout(ticket_layout)
        ticket_group.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed)
        chart_area.addWidget(ticket_group)
        middle.addLayout(chart_area, 3)

        side_panel = QtWidgets.QVBoxLayout()
        side_panel.setContentsMargins(0, 0, 0, 0)
        side_panel.setSpacing(4)

        ae_group = QtWidgets.QGroupBox("AE Snapshot")
        ae_layout = QtWidgets.QVBoxLayout()
        self.ae_status_label = QtWidgets.QLabel("AE: --")
        self.ae_status_label.setStyleSheet("color: #7f8c8d;")
        ae_layout.addWidget(self.ae_status_label)
        self.ae_row_regime = QtWidgets.QHBoxLayout()
        self.ae_row_context = QtWidgets.QHBoxLayout()
        self.ae_row_regime.setSpacing(4)
        self.ae_row_context.setSpacing(4)
        self.ae_pill_market = self._make_pill()
        self.ae_pill_ema = self._make_pill()
        self.ae_pill_vwap = self._make_pill()
        self.ae_pill_open = self._make_pill()
        self.ae_pill_macd = self._make_pill()
        self.ae_pill_quality = self._make_pill()
        for pill in [
            self.ae_pill_market,
            self.ae_pill_ema,
            self.ae_pill_vwap,
            self.ae_pill_open,
            self.ae_pill_macd,
            self.ae_pill_quality,
        ]:
            self.ae_row_regime.addWidget(pill)
        self.ae_row_regime.addStretch()

        self.ae_pill_range = self._make_pill()
        self.ae_pill_vol = self._make_pill()
        self.ae_pill_gap = self._make_pill()
        self.ae_pill_res_prox = self._make_pill()
        for pill in [self.ae_pill_range, self.ae_pill_vol, self.ae_pill_gap, self.ae_pill_res_prox]:
            self.ae_row_context.addWidget(pill)
        self.ae_row_context.addStretch()

        self.ae_levels_line1 = QtWidgets.QLabel("")
        self.ae_levels_line2 = QtWidgets.QLabel("")
        self.ae_levels_line1.setWordWrap(False)
        self.ae_levels_line2.setWordWrap(False)

        ae_layout.addLayout(self.ae_row_regime)
        ae_layout.addLayout(self.ae_row_context)
        ae_layout.addWidget(self.ae_levels_line1)
        ae_layout.addWidget(self.ae_levels_line2)
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

        fundamentals_group = QtWidgets.QGroupBox("Fundamentals")
        fundamentals_layout = QtWidgets.QVBoxLayout()
        fundamentals_layout.setContentsMargins(6, 4, 6, 6)
        fundamentals_layout.setSpacing(4)
        self.quote_label = QtWidgets.QLabel("Quote: --")
        fundamentals_layout.addWidget(self.quote_label)
        fundamentals_group.setLayout(fundamentals_layout)
        side_panel.addWidget(fundamentals_group)

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
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
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
        self._logger.debug("Quote label set to: %s", " | ".join(parts))

    @QtCore.Slot(float, float, float, float)
    def render_quote(self, ts_ms: float, bid: float, ask: float, last: float) -> None:
        """Thread-safe slot to update quote and connection labels."""
        self.connection_label.setText("Connection: STREAMING")
        if ts_ms:
            self.last_update_label.setText(f"Last Update: {int(ts_ms)}")
        self.update_quote_display(bid, ask, last, int(ts_ms) if ts_ms else None)

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
            self._reset_ae_ui()
            return
        self.ae_status_label.hide()
        self.ae_copy_btn.setEnabled(True)
        regime = snapshot.get("regime") or {}
        vol = snapshot.get("volatility") or {}
        volume = snapshot.get("volume") or {}
        levels = snapshot.get("levels") or {}
        session = snapshot.get("session") or {}
        data_quality = snapshot.get("data_quality")

        # Row A pills
        self._set_pill(
            self.ae_pill_market,
            "Market",
            self._color_for_bool(regime.get("is_market_green")),
            tooltip="Broad market proxy (SPY/QQQ).\nGreen = proxy up vs baseline; Red = down.\nSource: regime.is_market_green",
        )
        self._set_pill(
            self.ae_pill_ema,
            "4H EMA",
            self._color_for_bool(regime.get("is_above_4h_ema")),
            tooltip="Higher-timeframe trend filter.\nAbove = last HTF close above EMA(9); Below = under EMA.\nSource: regime.is_above_4h_ema",
        )
        self._set_pill(
            self.ae_pill_vwap,
            "VWAP",
            self._color_for_bool(regime.get("is_above_vwap")),
            tooltip="Session VWAP anchored 04:00–20:00 ET.\nAbove = price > VWAP; Below = price < VWAP.\nSource: regime.is_above_vwap + vwap + last_price",
        )
        self._set_pill(
            self.ae_pill_open,
            "Open",
            self._color_for_bool(regime.get("is_above_open")),
            tooltip="RTH open reference from 09:30 bar open.\nAbove = last_price > session_open_rth.\nSource: regime.is_above_open",
        )
        macd_ready = bool(regime.get("macd_ready"))
        macd_regime = regime.get("macd_regime")
        macd_text = "MACD"
        macd_color = "#7f8c8d" if not macd_ready else self._color_for_macd(macd_regime)
        macd_tooltip = (
            "Needs at least 30 completed 1m bars to compute.\nSource: regime.macd_ready"
            if not macd_ready
            else "MACD(12,26,9) on 1m closes.\nBullish = MACD line above signal; Bearish = below.\nSource: regime.macd_regime"
        )
        self._set_pill(self.ae_pill_macd, macd_text, macd_color, tooltip=macd_tooltip)
        self._set_pill(
            self.ae_pill_quality,
            "Quality",
            self._color_for_quality(data_quality),
            tooltip="Data freshness / completeness.\nok = live; stale/no_data = quote too old; partial = missing key datasets.\nSource: data_quality",
        )

        # Row B pills
        range_pct = vol.get("intraday_range_pct")
        self._set_pill(
            self.ae_pill_range,
            f"Range {_fmt_pct1(range_pct)}%",
            self._color_for_range(range_pct),
            tooltip="Intraday volatility: (session_high - session_low) / session_open.\nHigher range = more movement (momentum suitability).\nSource: volatility.intraday_range_pct",
        )
        vol_mult = volume.get("volume_multiple")
        self._set_pill(
            self.ae_pill_vol,
            f"Vol {_fmt_num(vol_mult)}x",
            self._color_for_volmult(vol_mult),
            tooltip="Relative 1m volume vs median of last 30 1m bars.\n>1.0x = above typical; <1.0x = below typical.\nSource: volume.volume_multiple",
        )
        gap_pct = session.get("gap_pct")
        self._set_pill(
            self.ae_pill_gap,
            f"Gap {_fmt_pct1(gap_pct)}%",
            self._color_for_gap(gap_pct),
            tooltip="Gap vs prior close: (session_open - prior_close) / prior_close.\nLarge gaps can increase volatility and risk.\nSource: session.gap_pct",
            visible=gap_pct is not None,
        )
        in_r_zone = levels.get("in_resistance_zone")
        next_r_pct = levels.get("distance_to_next_cluster_pct")
        if in_r_zone:
            self._set_pill(
                self.ae_pill_res_prox,
                "In R Zone",
                "#c0392b",
                tooltip="Resistance proximity based on structural clusters and/or key levels.\nIn R Zone = price inside a resistance zone.\nSource: levels.in_resistance_zone",
                visible=True,
            )
        elif next_r_pct is not None:
            self._set_pill(
                self.ae_pill_res_prox,
                f"Next R {_fmt_pct1(next_r_pct)}%",
                self._color_for_next_res(next_r_pct),
                tooltip="Resistance proximity based on structural clusters and/or key levels.\nNext R = distance to nearest resistance cluster above price.\nSource: levels.distance_to_next_cluster_pct",
                visible=True,
            )
        else:
            self._set_pill(self.ae_pill_res_prox, "", "#7f8c8d", visible=False)

        # Lines below pills
        nr = levels.get("nearest_resistance") or {}
        ns = levels.get("nearest_support") or {}
        line1_parts = []
        r_txt = self._format_level("R", nr)
        s_txt = self._format_level("S", ns)
        if r_txt:
            line1_parts.append(r_txt)
        if s_txt:
            line1_parts.append(s_txt)
        self.ae_levels_line1.setText("  |  ".join(line1_parts))

        or_high = session.get("opening_range_high")
        or_low = session.get("opening_range_low")
        pm_high = session.get("premarket_high")
        pm_low = session.get("premarket_low")
        line2_parts = []
        or_txt = self._format_range("OR", or_high, or_low)
        pm_txt = self._format_range("PM", pm_high, pm_low)
        if or_txt:
            line2_parts.append(or_txt)
        if pm_txt:
            line2_parts.append(pm_txt)
        self.ae_levels_line2.setText("  |  ".join(line2_parts))

    def _copy_ae_json(self) -> None:
        if not self._last_ae_snapshot:
            return
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(json.dumps(self._last_ae_snapshot, indent=2))

    def _reset_ae_ui(self) -> None:
        self.ae_status_label.setText("AE: Working…")
        self.ae_status_label.setStyleSheet("color: #7f8c8d;")
        self.ae_status_label.show()
        self.ae_copy_btn.setEnabled(False)
        for pill in [
            self.ae_pill_market,
            self.ae_pill_ema,
            self.ae_pill_vwap,
            self.ae_pill_open,
            self.ae_pill_macd,
            self.ae_pill_quality,
            self.ae_pill_range,
            self.ae_pill_vol,
            self.ae_pill_gap,
            self.ae_pill_res_prox,
        ]:
            pill.setText("--")
            pill.setStyleSheet(self._pill_stylesheet("#7f8c8d", "#ffffff"))
            pill.setVisible(True)
            pill.setToolTip("")
        self.ae_levels_line1.setText("")
        self.ae_levels_line2.setText("")

    def _make_pill(self) -> QtWidgets.QLabel:
        pill = QtWidgets.QLabel("--")
        pill.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        pill.setMargin(2)
        pill.setStyleSheet(self._pill_stylesheet("#7f8c8d", "#ffffff"))
        pill.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        return pill

    @staticmethod
    def _pill_stylesheet(bg: str, fg: str) -> str:
        return (
            f"QLabel {{ background-color: {bg}; color: {fg}; border-radius: 4px; padding: 1px 4px; "
            f"font-weight: bold; }}"
        )

    def _set_pill(self, pill: QtWidgets.QLabel, text: str, color: str, tooltip: str = "", visible: bool = True) -> None:
        pill.setText(text)
        pill.setStyleSheet(self._pill_stylesheet(color, "#ffffff"))
        pill.setToolTip(tooltip)
        pill.setVisible(visible)

    @staticmethod
    def _pill_text(label: str, value: str) -> str:
        if value and value != "--":
            return f"{label}: {value}"
        return label

    @staticmethod
    def _label_bool(val: bool | None, true_label: str, false_label: str) -> str:
        if val is True:
            return true_label
        if val is False:
            return false_label
        return "--"

    @staticmethod
    def _color_for_bool(val: bool | None) -> str:
        if val is True:
            return "#27ae60"
        if val is False:
            return "#c0392b"
        return "#7f8c8d"

    @staticmethod
    def _color_for_quality(val: str | None) -> str:
        if val == "ok":
            return "#27ae60"
        if val in ("stale", "partial"):
            return "#f39c12"
        if val == "no_data":
            return "#c0392b"
        return "#7f8c8d"

    @staticmethod
    def _color_for_macd(regime: str | None) -> str:
        if regime == "bullish":
            return "#27ae60"
        if regime == "bearish":
            return "#c0392b"
        return "#7f8c8d"

    @staticmethod
    def _color_for_range(val: float | None) -> str:
        if val is None:
            return "#7f8c8d"
        if val < 10:
            return "#95a5a6"
        if val < 25:
            return "#27ae60"
        if val < 60:
            return "#f39c12"
        return "#c0392b"

    @staticmethod
    def _color_for_volmult(val: float | None) -> str:
        if val is None:
            return "#7f8c8d"
        if val < 0.8:
            return "#95a5a6"
        if val <= 1.2:
            return "#27ae60"
        return "#2ecc71"

    @staticmethod
    def _color_for_gap(val: float | None) -> str:
        if val is None:
            return "#7f8c8d"
        if abs(val) < 2:
            return "#27ae60"
        return "#f39c12"

    @staticmethod
    def _color_for_next_res(val: float | None) -> str:
        if val is None:
            return "#7f8c8d"
        if val < 0.5:
            return "#c0392b"
        if val < 2:
            return "#f39c12"
        return "#95a5a6"

    def _format_level(self, label: str, lvl: dict) -> str:
        if not lvl or lvl.get("price") is None:
            return ""
        price = _fmt_price(lvl.get("price"))
        dist = lvl.get("distance_pct")
        dist_txt = f"{_fmt_pct(dist)}%" if dist is not None else ""
        source = lvl.get("source") or ""
        parts = [f"{label}: {price}"]
        if dist_txt:
            parts.append(f"({dist_txt})")
        if source:
            parts.append(f"[{source}]")
        return " ".join(parts)

    @staticmethod
    def _format_range(label: str, high: float | None, low: float | None) -> str:
        if high is None and low is None:
            return ""
        hi_txt = _fmt_price(high) if high is not None else "--"
        lo_txt = _fmt_price(low) if low is not None else "--"
        return f"{label}: {hi_txt}/{lo_txt}"


def _fmt_pct(val: float | None) -> str:
    if val is None:
        return "--"
    return f"{val:.2f}"


def _fmt_num(val: float | None) -> str:
    if val is None:
        return "--"
    return f"{val:.1f}"


def _fmt_pct1(val: float | None) -> str:
    if val is None:
        return "--"
    return f"{val:.1f}"


def _fmt_price(val: float | None) -> str:
    if val is None:
        return "--"
    return f"{val:.2f}"
