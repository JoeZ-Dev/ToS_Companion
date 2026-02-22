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
        self._options_dialog: QtWidgets.QDialog | None = None

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
        self.symbol_input.setValidator(None)
        top.addWidget(self.symbol_input)
        self.connection_label = QtWidgets.QLabel("Connection: UNKNOWN")
        top.addWidget(self.connection_label)
        self.options_btn = QtWidgets.QPushButton("Options")
        top.addWidget(self.options_btn)
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
        self.ae_pill_state = self._make_pill()
        self.ae_pill_micro_r = self._make_pill()
        for pill in [self.ae_pill_state, self.ae_pill_range, self.ae_pill_vol, self.ae_pill_gap, self.ae_pill_micro_r, self.ae_pill_res_prox]:
            self.ae_row_context.addWidget(pill)
        self.ae_row_context.addStretch()

        self.ae_levels_line1 = QtWidgets.QLabel("")
        self.ae_levels_line2 = QtWidgets.QLabel("")
        self.ae_levels_line3 = QtWidgets.QLabel("")
        self.ae_levels_line4 = QtWidgets.QLabel("")
        self.ae_levels_line1.setWordWrap(False)
        self.ae_levels_line2.setWordWrap(False)
        self.ae_levels_line3.setWordWrap(False)
        self.ae_levels_line4.setWordWrap(False)
        self.ae_levels_line1.setToolTip("Nearest structural resistance/support with distance % and source.")
        self.ae_levels_line2.setToolTip("Opening Range (09:30–09:40 ET) and Premarket (04:00–09:30 ET) highs/lows.")
        self.ae_levels_line3.setToolTip("Micro context: 15m swing R/S and recent 5m/15m ranges from 1m bars.")
        self.ae_levels_line4.setToolTip("Top influenced levels (macro/micro) ranked by dynamic_influence.")
        self.ae_levels_line4.setWordWrap(True)

        ae_layout.addLayout(self.ae_row_regime)
        ae_layout.addLayout(self.ae_row_context)
        ae_layout.addWidget(self.ae_levels_line1)
        ae_layout.addWidget(self.ae_levels_line2)
        ae_layout.addWidget(self.ae_levels_line3)
        ae_layout.addWidget(self.ae_levels_line4)
        self.ae_copy_btn = QtWidgets.QPushButton("Copy Data")
        self.ae_copy_btn.setFlat(True)
        self.ae_copy_btn.setStyleSheet("text-decoration: underline; color: #2980b9;")
        self.ae_copy_btn.clicked.connect(self._copy_ae_json)
        ae_layout.addWidget(self.ae_copy_btn, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        ae_group.setLayout(ae_layout)
        side_panel.addWidget(ae_group)

        llm_group = QtWidgets.QGroupBox("LLM Panel")
        llm_layout = QtWidgets.QVBoxLayout()
        llm_layout.setSpacing(4)
        llm_top = QtWidgets.QHBoxLayout()
        self.llm_status = QtWidgets.QLabel("LLM: OFF")
        self.llm_toggle = QtWidgets.QPushButton("Enable LLM")
        self.llm_toggle.setCheckable(True)
        self.llm_toggle.setChecked(False)
        llm_top.addWidget(self.llm_status)
        llm_top.addWidget(self.llm_toggle)
        llm_top.addStretch()
        llm_layout.addLayout(llm_top)
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
        self.quote_last = QtWidgets.QLabel("Last: --")
        self.quote_bid = QtWidgets.QLabel("Bid: --")
        self.quote_ask = QtWidgets.QLabel("Ask: --")
        self.quote_float = QtWidgets.QLabel("Float: --")
        self.quote_last.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self.quote_bid.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self.quote_ask.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self.quote_float.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        fundamentals_layout.addWidget(self.quote_last)
        fundamentals_layout.addWidget(self.quote_bid)
        fundamentals_layout.addWidget(self.quote_ask)
        fundamentals_layout.addWidget(self.quote_float)
        fundamentals_group.setLayout(fundamentals_layout)
        fundamentals_group.setStyleSheet(
            "QGroupBox { margin-top: 8px; } QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 2px 6px; }"
        )
        side_panel.addWidget(fundamentals_group)

        status_group = QtWidgets.QGroupBox("Status")
        status_layout = QtWidgets.QVBoxLayout()
        status_layout.setContentsMargins(6, 4, 6, 4)
        status_layout.setSpacing(2)
        self.stream_label = QtWidgets.QLabel("Stream: CONNECTED")
        self.token_label = QtWidgets.QLabel("Auth: OK")
        self.last_update_label = QtWidgets.QLabel("Last Update:")
        status_layout.addWidget(self.stream_label)
        status_layout.addWidget(self.token_label)
        status_layout.addWidget(self.last_update_label)
        status_group.setLayout(status_layout)
        status_group.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed)
        side_panel.addWidget(status_group)
        side_panel.setStretchFactor(ae_group, 3)
        side_panel.setStretchFactor(llm_group, 1)
        side_panel.setStretchFactor(fundamentals_group, 1)
        side_panel.setStretchFactor(status_group, 0)
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
        self.quote_last.setText(f"Last: {last:.2f}" if last is not None else "Last: --")
        self.quote_bid.setText(f"Bid: {bid:.2f}" if bid is not None else "Bid: --")
        self.quote_ask.setText(f"Ask: {ask:.2f}" if ask is not None else "Ask: --")
        self._logger.debug("Quote labels set to last=%s bid=%s ask=%s", last, bid, ask)

    def update_float(self, shares_outstanding: float | None) -> None:
        """Display float using sharesOutstanding fundamental field."""
        if shares_outstanding is None:
            self.quote_float.setText("Float: --")
            return
        human = _fmt_human_shares(shares_outstanding)
        self.quote_float.setText(f"Float: {human}")

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

    def show_options_dialog(self) -> None:
        if self._options_dialog is None:
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("Options")
            dlg.setModal(True)
            dlg.setStyleSheet(
                """
                QDialog { background-color: #111; color: #ecf0f1; }
                QLabel { color: #ecf0f1; }
                QPushButton { background-color: #2c3e50; color: #ecf0f1; padding: 4px 8px; border: 1px solid #34495e; }
                QPushButton:hover { background-color: #34495e; }
                """
            )
            layout = QtWidgets.QVBoxLayout()
            layout.addWidget(QtWidgets.QLabel("Options placeholder"))
            close_btn = QtWidgets.QPushButton("Close")
            close_btn.clicked.connect(dlg.close)
            layout.addWidget(close_btn, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
            dlg.setLayout(layout)
            self._options_dialog = dlg
        self._options_dialog.show()

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
        micro = snapshot.get("micro") or {}
        levels_book = snapshot.get("levels_book") or []

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
        macd_text = "MACD" if macd_ready else "MACD Warming"
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
        micro_state = micro.get("micro_state")
        self._set_pill(
            self.ae_pill_state,
            f"State: {micro_state if micro_state else '--'}",
            self._color_for_state(micro_state),
            tooltip="COIL = tight short-term range vs 15m range.\nEXPAND = short-term range widening.\nBased on 5m/15m range from 1m bars.",
            visible=bool(micro_state),
        )
        range_pct = vol.get("intraday_range_pct")
        range_text = f"Range {_fmt_pct1(range_pct)}%"
        if range_pct is not None and range_pct > 60:
            range_text = f"{range_text} \U0001F525"
        self._set_pill(
            self.ae_pill_range,
            range_text,
            self._color_for_range(range_pct),
            tooltip="Intraday volatility: (session_high - session_low) / session_open.\nHigher range = more movement/opportunity for longs.\nSource: volatility.intraday_range_pct",
        )
        vol_mult = volume.get("volume_multiple")
        self._set_pill(
            self.ae_pill_vol,
            f"Vol {_fmt_num(vol_mult)}x",
            self._color_for_volmult(vol_mult),
            tooltip="Relative 1m volume vs median of last 30 1m bars.\nWe want 3x+ for strong momentum confirmation.\nSource: volume.volume_multiple",
        )
        gap_pct = session.get("gap_pct")
        gap_text = f"Gap {_fmt_pct1_signed(gap_pct)}%"
        self._set_pill(
            self.ae_pill_gap,
            gap_text,
            self._color_for_gap(gap_pct),
            tooltip="Gap vs prior close: (session_open - prior_close) / prior_close.\nRunner filter: we mainly care about 30%+ gaps.\nSource: session.gap_pct",
            visible=gap_pct is not None,
        )
        in_r_zone = levels.get("in_resistance_zone")
        next_r_pct = levels.get("distance_to_next_cluster_pct")
        last_price = snapshot.get("last_price")
        res_price = (levels.get("nearest_resistance") or {}).get("price")
        micro_dist = micro.get("dist_to_micro_r_pct")
        if micro_dist is not None and micro_dist <= 1.0:
            self._set_pill(
                self.ae_pill_micro_r,
                f"Micro R: {_fmt_pct1(micro_dist)}%",
                self._color_for_micro_r(micro_dist),
                tooltip="Distance to 15-minute swing high (micro resistance).",
                visible=True,
            )
        else:
            self._set_pill(self.ae_pill_micro_r, "Micro R: --", "#7f8c8d", visible=False)
        if in_r_zone:
            self._set_pill(
                self.ae_pill_res_prox,
                "In R Zone",
                "#c0392b",
                tooltip="Resistance proximity based on structural clusters and/or key levels.\nIn R Zone = price inside a resistance zone.\nSource: levels.in_resistance_zone",
                visible=True,
            )
        elif next_r_pct is not None:
            text = f"Next R {_fmt_pct1(next_r_pct)}%"
            if last_price is not None and res_price is not None:
                delta = res_price - last_price
                if delta > 0:
                    text = f"{text} (+${delta:.2f})"
            self._set_pill(
                self.ae_pill_res_prox,
                text,
                self._color_for_next_res(next_r_pct),
                tooltip="Resistance proximity for continuation.\nMore distance = more runway for longs.\nSource: levels.distance_to_next_cluster_pct",
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
        micro_line = f"Micro: R {_fmt_price(micro.get('micro_resistance_15m'))} | S {_fmt_price(micro.get('micro_support_15m'))} | 5mRng {_fmt_pct1(micro.get('range_5m_pct'))}% | 15mRng {_fmt_pct1(micro.get('range_15m_pct'))}%"
        self.ae_levels_line3.setText(micro_line)
        influ_parts = []
        res_levels = [lvl for lvl in levels_book if lvl.get("side") == "resistance"]
        sup_levels = [lvl for lvl in levels_book if lvl.get("side") == "support"]

        def fmt_levels(levels: list[dict], prefix: str) -> str:
            items = []
            for idx, lvl in enumerate(levels[:3], 1):
                price_val = lvl.get("high") if lvl.get("high") is not None else lvl.get("low")
                price = _fmt_price(price_val)
                inf = _fmt_influence(lvl.get("dynamic_influence"))
                items.append(f"{idx}) {price} ({inf})")
            return f"{prefix}: " + " | ".join(items) if items else ""

        res_text = fmt_levels(res_levels, "R")
        sup_text = fmt_levels(sup_levels, "S")
        line4_text = "Influence"
        if res_text:
            line4_text += f" {res_text}"
        if sup_text:
            line4_text += ("  " if res_text else " ") + sup_text
        self.ae_levels_line4.setText(line4_text if (res_text or sup_text) else "")

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
            self.ae_pill_state,
            self.ae_pill_range,
            self.ae_pill_vol,
            self.ae_pill_gap,
            self.ae_pill_micro_r,
            self.ae_pill_res_prox,
        ]:
            pill.setText("--")
            pill.setStyleSheet(self._pill_stylesheet("#7f8c8d", "#ffffff"))
            pill.setVisible(True)
            pill.setToolTip("")
        self.ae_levels_line1.setText("")
        self.ae_levels_line2.setText("")
        self.ae_levels_line3.setText("")
        self.ae_levels_line4.setText("")

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
    def _color_for_state(state: str | None) -> str:
        if state == "EXPAND":
            return "#27ae60"
        if state == "COIL":
            return "#f1c40f"
        if state == "NEUTRAL":
            return "#95a5a6"
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
            return "#2ecc71"
        return "#8e44ad"

    @staticmethod
    def _color_for_volmult(val: float | None) -> str:
        if val is None:
            return "#7f8c8d"
        if val < 2.0:
            return "#95a5a6"
        if val < 3.0:
            return "#27ae60"
        return "#2ecc71"

    @staticmethod
    def _color_for_gap(val: float | None) -> str:
        if val is None:
            return "#7f8c8d"
        abs_gap = abs(val)
        if abs_gap < 10:
            return "#95a5a6"
        if abs_gap < 30:
            return "#27ae60"
        if abs_gap < 60:
            return "#2ecc71"
        return "#8e44ad"

    @staticmethod
    def _color_for_next_res(val: float | None) -> str:
        if val is None:
            return "#7f8c8d"
        if val < 0.5:
            return "#c0392b"
        if val < 2:
            return "#f39c12"
        if val < 5:
            return "#a3d9a5"
        if val < 10:
            return "#27ae60"
        return "#2ecc71"

    @staticmethod
    def _color_for_micro_r(val: float | None) -> str:
        if val is None:
            return "#7f8c8d"
        if val < 0.25:
            return "#c0392b"
        if val <= 1.0:
            return "#f39c12"
        return "#7f8c8d"

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

def _fmt_pct1_signed(val: float | None) -> str:
    if val is None:
        return "--"
    return f"{val:+.1f}"


def _fmt_price(val: float | None) -> str:
    if val is None:
        return "--"
    return f"{val:.2f}"

def _fmt_influence(val: float | None) -> str:
    if val is None:
        return "--"
    return f"{val:.2f}"


def _fmt_human_shares(val: float) -> str:
    scaled = float(val)
    # Round to nearest 100k for readability
    scaled = round(scaled / 100_000) * 100_000
    if scaled >= 1_000_000_000:
        return f"{scaled / 1_000_000_000:.2f}B"
    if scaled >= 1_000_000:
        return f"{scaled / 1_000_000:.2f}M"
    if scaled >= 1_000:
        return f"{scaled / 1_000:.2f}K"
    return f"{scaled:.0f}"
