from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

import pandas as pd

from momentum_companion.clients.schwab_rest import SchwabRestClient
from momentum_companion.data.bar_aggregator import TenSecondBar


ET_TZ = ZoneInfo("America/New_York")
PREMARKET_START = timedelta(hours=4)
RTH_START = timedelta(hours=9, minutes=30)
RTH_END = timedelta(hours=16)
AFTERHOURS_END = timedelta(hours=20)
OPENING_RANGE_MINUTES = 10
VWAP_ANCHOR_START = PREMARKET_START
VWAP_ANCHOR_END = AFTERHOURS_END
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
MACD_MIN_BARS = 30
VOLUME_BASELINE_WINDOW = 30
EMA9_PERIOD = 9
SWING_LOOKBACK = 3
MICRO_WINDOW_5M = 5
MICRO_WINDOW_15M = 15
CLUSTER_BAND_PCT = 0.015
CLUSTER_CAP = 3
CLUSTER_POOL_CAP = 50
HALF_LIFE_4H = 40
HALF_LIFE_DAILY = 60
VOLATILITY_THRESHOLD = 1.0
STALE_IF_QUOTE_AGE_MS = 5_000
NO_DATA_IF_QUOTE_AGE_MS = 60_000
STRENGTH_DENOM = 1.0  # used to normalize raw strength
ZERO_WIDTH_BAND_PCT = 0.0001  # 0.01% expansion for zero-width zones

MARKET_PROXY_SYMBOL = "SPY"


@dataclass
class OneMinuteBar:
    ts: int  # epoch seconds at bar start
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_extended: bool


class MinuteBarAggregator:
    """Aggregate completed 10s bars into 1m bars and maintain session stats."""

    def __init__(self) -> None:
        self._current: Optional[OneMinuteBar] = None
        self._bars: list[OneMinuteBar] = []
        self._volumes: list[float] = []
        self.last_seeded_minute_ts: Optional[int] = None
        self.session_high: Optional[float] = None
        self.session_low: Optional[float] = None
        self.vwap_num: float = 0.0
        self.vwap_den: float = 0.0
        self.premarket_high: Optional[float] = None
        self.premarket_low: Optional[float] = None
        self.or_high: Optional[float] = None
        self.or_low: Optional[float] = None
        self.session_open: Optional[float] = None

    @property
    def bars(self) -> list[OneMinuteBar]:
        return list(self._bars)

    def ingest_10s(self, bar: TenSecondBar) -> Optional[OneMinuteBar]:
        ts_minute = (bar.ts // 60) * 60
        completed: Optional[OneMinuteBar] = None
        if self._current is None or ts_minute > self._current.ts:
            if self._current is not None:
                completed = self._current
                self._store_completed_minute(self._current)
            self._current = OneMinuteBar(
                ts=ts_minute,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                is_extended=bar.is_extended,
            )
        else:
            self._current.high = max(self._current.high, bar.high)
            self._current.low = min(self._current.low, bar.low)
            self._current.close = bar.close
            self._current.volume += bar.volume
            self._current.is_extended = self._current.is_extended or bar.is_extended

        self._update_session_stats(bar)
        return completed

    def _store_completed_minute(self, bar: OneMinuteBar) -> None:
        replaced = False
        if self.last_seeded_minute_ts is not None and bar.ts == self.last_seeded_minute_ts:
            self._remove_seeded_minute_from_vwap(bar.ts)
            if self._bars and self._bars[-1].ts == bar.ts:
                self._bars[-1] = bar
                if self._volumes:
                    self._volumes[-1] = bar.volume
                else:
                    self._volumes.append(bar.volume)
                replaced = True
            else:
                for idx, existing in enumerate(self._bars):
                    if existing.ts == bar.ts:
                        self._bars[idx] = bar
                        if idx < len(self._volumes):
                            self._volumes[idx] = bar.volume
                        else:
                            self._volumes.append(bar.volume)
                        replaced = True
                        break
            self.last_seeded_minute_ts = None
        if not replaced:
            self._bars.append(bar)
            self._volumes.append(bar.volume)
        if len(self._volumes) > 300:
            self._volumes = self._volumes[-300:]

    def _remove_seeded_minute_from_vwap(self, ts: int) -> None:
        target_bar: Optional[OneMinuteBar] = None
        for b in reversed(self._bars):
            if b.ts == ts:
                target_bar = b
                break
        if target_bar is None:
            return
        ts_et = datetime.fromtimestamp(target_bar.ts, tz=timezone.utc).astimezone(ET_TZ)
        tod = timedelta(hours=ts_et.hour, minutes=ts_et.minute, seconds=ts_et.second)
        if tod < VWAP_ANCHOR_START or tod > VWAP_ANCHOR_END:
            return
        self.vwap_num = max(0.0, self.vwap_num - target_bar.close * target_bar.volume)
        self.vwap_den = max(0.0, self.vwap_den - target_bar.volume)

    def _update_session_stats(self, bar: TenSecondBar) -> None:
        ts_et = datetime.fromtimestamp(bar.ts, tz=timezone.utc).astimezone(ET_TZ)
        tod = timedelta(hours=ts_et.hour, minutes=ts_et.minute, seconds=ts_et.second)
        price_high = bar.high
        price_low = bar.low
        if tod >= PREMARKET_START and tod < RTH_START:
            self.premarket_high = price_high if self.premarket_high is None else max(self.premarket_high, price_high)
            self.premarket_low = price_low if self.premarket_low is None else min(self.premarket_low, price_low)
        if tod >= RTH_START:
            if self.session_open is None:
                self.session_open = bar.open
            if tod < RTH_START + timedelta(minutes=OPENING_RANGE_MINUTES):
                self.or_high = price_high if self.or_high is None else max(self.or_high, price_high)
                self.or_low = price_low if self.or_low is None else min(self.or_low, price_low)
        self.session_high = price_high if self.session_high is None else max(self.session_high, price_high)
        self.session_low = price_low if self.session_low is None else min(self.session_low, price_low)
        if tod >= VWAP_ANCHOR_START and tod <= VWAP_ANCHOR_END:
            self.vwap_num += bar.close * bar.volume
            self.vwap_den += bar.volume

    def vwap(self) -> Optional[float]:
        if self.vwap_den == 0:
            return None
        return self.vwap_num / self.vwap_den

    def rolling_volume_median(self) -> Optional[float]:
        window = self._volumes[-VOLUME_BASELINE_WINDOW :]
        if not window:
            return None
        return float(pd.Series(window).median())


def _fractal_indices(series: pd.Series, lookback: int, mode: str) -> list[int]:
    idxs: list[int] = []
    for i in range(lookback, len(series) - lookback):
        window = series.iloc[i - lookback : i + lookback + 1]
        if mode == "high" and series.iloc[i] == window.max():
            idxs.append(i)
        if mode == "low" and series.iloc[i] == window.min():
            idxs.append(i)
    return idxs


def _cluster_swings(prices: pd.Series, lookback: int, band_pct: float, cap: int, half_life: int, mode: str) -> list[Dict[str, float]]:
    indices = _fractal_indices(prices, lookback, "high" if mode == "resistance" else "low")
    swings = prices.iloc[indices]
    zones: list[Dict[str, float]] = []
    used = [False] * len(swings)
    for i, (idx, price) in enumerate(swings.items()):
        if used[i]:
            continue
        band = price * band_pct
        if band == 0:
            band = price * ZERO_WIDTH_BAND_PCT
        members = swings[(swings >= price - band) & (swings <= price + band)]
        for j, _ in enumerate(swings):
            if swings.index[j] in members.index:
                used[j] = True
        zone_low = members.min()
        zone_high = members.max()
        touches = len(members)
        age = len(prices) - idx
        recency = math.exp(-age / half_life) if half_life > 0 else 0
        raw_strength = touches * (0.5 + 0.5 * recency)
        normalized_strength = min(1.0, raw_strength / (raw_strength + STRENGTH_DENOM))
        zones.append({"price_zone_low": float(zone_low), "price_zone_high": float(zone_high), "strength_score": float(normalized_strength)})
    zones = sorted(zones, key=lambda z: z["strength_score"], reverse=True)[:cap]
    return zones


class AEEngine:
    """Analysis Engine orchestrator for AE-1.0 profile and AE-1.1 snapshots."""

    def __init__(self, rest_client: Optional[SchwabRestClient], db_path: Optional[Path]) -> None:
        self._rest = rest_client
        self._db_path = db_path
        self._profile_cache: dict[str, dict] = {}
        self._snapshot_cache: dict[str, dict] = {}
        self._minute_agg = MinuteBarAggregator()
        self._last_quote_ms: Optional[int] = None
        self._market_cache: Optional[tuple[int, bool, Optional[bool]]] = None  # (ts_ms, has_market_data, is_market_green)
        self._session_open_rth: dict[str, Optional[float]] = {}
        self._active_symbol: Optional[str] = None
        self._seeded = False

    def reset_intraday(self) -> None:
        self._minute_agg = MinuteBarAggregator()
        self._snapshot_cache.clear()
        self._last_quote_ms = None
        self._market_cache = None
        self._seeded = False
        self._active_symbol = None

    def record_quote_ts(self, ts_ms: int) -> None:
        self._last_quote_ms = ts_ms

    def compute_profile(self, symbol: str) -> Optional[dict]:
        if not self._rest:
            return None
        try:
            bars, source_tf = self._fetch_htf(symbol)
        except Exception:
            return None
        if bars.empty or "close" not in bars:
            return None
        ema = bars["close"].ewm(span=EMA9_PERIOD, adjust=False).mean()
        is_above_ema = bool(bars["close"].iloc[-1] > ema.iloc[-1])
        prior_close = float(bars["close"].iloc[-1])
        half_life = HALF_LIFE_4H if source_tf == "4h" else HALF_LIFE_DAILY
        res_clusters = _cluster_swings(bars["high"], SWING_LOOKBACK, CLUSTER_BAND_PCT, CLUSTER_POOL_CAP, half_life, "resistance")
        sup_clusters = _cluster_swings(bars["low"], SWING_LOOKBACK, CLUSTER_BAND_PCT, CLUSTER_POOL_CAP, half_life, "support")
        htf_high = float(bars["high"].max())
        session_open_rth = self._fetch_rth_open(symbol)
        now_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        profile = {
            "symbol": symbol,
            "created_at_utc": now_utc,
            "is_above_4h_ema": is_above_ema,
            "prior_close": prior_close,
            "htf_high": htf_high,
            "session_open_rth": session_open_rth,
            "resistance_clusters": [{"timeframe_source": source_tf, **z} for z in res_clusters],
            "support_clusters": [{"timeframe_source": source_tf, **z} for z in sup_clusters],
        }
        self._profile_cache[symbol] = profile
        if self._db_path:
            self._store_profile(symbol, profile)
        self._session_open_rth[symbol] = session_open_rth
        return profile

    def _store_profile(self, symbol: str, profile: dict) -> None:
        if not self._db_path:
            return
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "INSERT INTO market_profile (symbol, created_at_utc, profile_json) VALUES (?, ?, ?)",
                (symbol, profile["created_at_utc"], json.dumps(profile)),
            )
            conn.commit()

    def _fetch_htf(self, symbol: str) -> tuple[pd.DataFrame, str]:
        assert self._rest is not None
        try:
            resp = self._rest.fetch_price_history(symbol, None, None, "4h")
            candles = resp.get("candles") or []
            if candles:
                return _candles_to_df(candles), "4h"
        except Exception:
            pass
        resp = self._rest.fetch_price_history(symbol, None, None, "1d")
        candles = resp.get("candles") or []
        return _candles_to_df(candles), "daily"

    def _fetch_rth_open(self, symbol: str) -> Optional[float]:
        if not self._rest:
            return None
        try:
            now_et = datetime.now(ET_TZ)
            start = datetime(now_et.year, now_et.month, now_et.day, 9, 30, tzinfo=ET_TZ)
            end = start + timedelta(minutes=1)
            resp = self._rest.fetch_price_history(symbol, int(start.timestamp() * 1000), int(end.timestamp() * 1000), "1m")
            candles = resp.get("candles") or []
            if not candles:
                return None
            candle = sorted(candles, key=lambda c: c.get("datetime", 0))[0]
            return float(candle.get("open")) if candle.get("open") is not None else None
        except Exception:
            return None

    def ingest_10s_bar(self, bar: TenSecondBar) -> Optional[dict]:
        completed_minute = self._minute_agg.ingest_10s(bar)
        if completed_minute is None:
            return None
        return self._build_snapshot()

    def seed_intraday_from_history(self, symbol: str) -> Optional[dict]:
        """
        Seed minute aggregator from REST 1m history (preferred: today 04:00 ET → now).
        Returns initial snapshot if successful.
        """
        if not self._rest:
            return None
        try:
            self._active_symbol = symbol
            self._minute_agg.premarket_high = None
            self._minute_agg.premarket_low = None
            self._minute_agg.or_high = None
            self._minute_agg.or_low = None
            self._minute_agg.session_open = None
            self._minute_agg.session_high = None
            self._minute_agg.session_low = None
            self._minute_agg.last_seeded_minute_ts = None
            now_et = datetime.now(ET_TZ)
            start_et = datetime(now_et.year, now_et.month, now_et.day, 4, 0, tzinfo=ET_TZ)
            start_ms = int(start_et.timestamp() * 1000)
            end_ms = int(now_et.timestamp() * 1000)
            resp = self._rest.fetch_price_history(symbol, start_ms, end_ms, "1m")
            candles = resp.get("candles") or []
            seeded = 0
            last_seed_ts = None
            for c in sorted(candles, key=lambda x: x.get("datetime", 0)):
                ts = c.get("datetime")
                if ts is None:
                    continue
                b = OneMinuteBar(
                    ts=int(ts // 1000),
                    open=c.get("open"),
                    high=c.get("high"),
                    low=c.get("low"),
                    close=c.get("close"),
                    volume=c.get("volume") or 0.0,
                    is_extended=0,
                )
                self._minute_agg._bars.append(b)
                self._minute_agg._volumes.append(b.volume)
                seeded += 1
                last_seed_ts = b.ts
            if seeded == 0:
                return None
            self._minute_agg.last_seeded_minute_ts = last_seed_ts
            # Compute VWAP from seeded bars within anchor window
            vnum = 0.0
            vden = 0.0
            for b in self._minute_agg._bars:
                ts_et = datetime.fromtimestamp(b.ts, tz=timezone.utc).astimezone(ET_TZ)
                tod = timedelta(hours=ts_et.hour, minutes=ts_et.minute, seconds=ts_et.second)
                if tod >= VWAP_ANCHOR_START and tod <= VWAP_ANCHOR_END:
                    vnum += b.close * b.volume
                    vden += b.volume
            self._minute_agg.vwap_num = vnum
            self._minute_agg.vwap_den = vden
            self._reconstruct_session_state_from_seeded()
            self._seeded = True
            return self._build_snapshot(symbol)
        except Exception:
            return None

    def _reconstruct_session_state_from_seeded(self) -> None:
        agg = self._minute_agg
        agg.session_high = None
        agg.session_low = None
        agg.premarket_high = None
        agg.premarket_low = None
        agg.or_high = None
        agg.or_low = None
        agg.session_open = None
        for b in agg._bars:
            ts_et = datetime.fromtimestamp(b.ts, tz=timezone.utc).astimezone(ET_TZ)
            tod = timedelta(hours=ts_et.hour, minutes=ts_et.minute, seconds=ts_et.second)
            price_high = b.high
            price_low = b.low
            if tod >= PREMARKET_START and tod < RTH_START:
                agg.premarket_high = price_high if agg.premarket_high is None else max(agg.premarket_high, price_high)
                agg.premarket_low = price_low if agg.premarket_low is None else min(agg.premarket_low, price_low)
            if tod >= RTH_START:
                if agg.session_open is None:
                    agg.session_open = b.open
                if tod < RTH_START + timedelta(minutes=OPENING_RANGE_MINUTES):
                    agg.or_high = price_high if agg.or_high is None else max(agg.or_high, price_high)
                    agg.or_low = price_low if agg.or_low is None else min(agg.or_low, price_low)
            agg.session_high = price_high if agg.session_high is None else max(agg.session_high, price_high)
            agg.session_low = price_low if agg.session_low is None else min(agg.session_low, price_low)

    def _resolve_symbol(self, symbol: Optional[str]) -> Optional[str]:
        if symbol:
            return symbol
        if self._active_symbol:
            return self._active_symbol
        if len(self._profile_cache) == 1:
            return list(self._profile_cache.keys())[0]
        return None

    def _build_snapshot(self, symbol: Optional[str] = None) -> dict:
        resolved_symbol = self._resolve_symbol(symbol)
        profile = self._profile_cache.get(resolved_symbol) if resolved_symbol else None

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        quote_age = None
        if self._last_quote_ms is not None:
            quote_age = now_ms - self._last_quote_ms
        status = "ok"
        data_quality = "ok"
        intraday_symbol_matches = resolved_symbol is None or self._active_symbol is None or resolved_symbol == self._active_symbol
        agg_bars = self._minute_agg.bars if intraday_symbol_matches else []
        has_intraday = bool(agg_bars)
        has_4h = profile is not None
        session_open_val = self._minute_agg.session_open if intraday_symbol_matches else None
        session_high_val = self._minute_agg.session_high if intraday_symbol_matches else None
        session_low_val = self._minute_agg.session_low if intraday_symbol_matches else None
        premarket_high_val = self._minute_agg.premarket_high if intraday_symbol_matches else None
        premarket_low_val = self._minute_agg.premarket_low if intraday_symbol_matches else None
        or_high_val = self._minute_agg.or_high if intraday_symbol_matches else None
        or_low_val = self._minute_agg.or_low if intraday_symbol_matches else None
        vwap_val = self._minute_agg.vwap() if intraday_symbol_matches else None
        if quote_age is not None and quote_age > NO_DATA_IF_QUOTE_AGE_MS:
            data_quality = "no_data"
        elif quote_age is not None and quote_age > STALE_IF_QUOTE_AGE_MS:
            data_quality = "stale"

        last_price = agg_bars[-1].close if agg_bars else None
        intraday_range_pct = None
        is_volatile = None
        if session_high_val and session_low_val and session_open_val:
            intraday_range_pct = ((session_high_val - session_low_val) / session_open_val * 100)
            is_volatile = intraday_range_pct > VOLATILITY_THRESHOLD

        macd_regime = None
        if len(agg_bars) >= MACD_MIN_BARS:
            closes = pd.Series([b.close for b in agg_bars])
            ema_fast = closes.ewm(span=MACD_FAST, adjust=False).mean()
            ema_slow = closes.ewm(span=MACD_SLOW, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            signal = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
            last_macd = macd_line.iloc[-1]
            last_signal = signal.iloc[-1]
            if last_macd > last_signal:
                macd_regime = "bullish"
            elif last_macd < last_signal:
                macd_regime = "bearish"
            else:
                macd_regime = "neutral"

        vol_mult = None
        baseline = self._minute_agg.rolling_volume_median() if intraday_symbol_matches else None
        if baseline is not None and baseline > 0 and agg_bars:
            vol_mult = agg_bars[-1].volume / baseline

        is_above_open = None
        rth_open = self._session_open_rth.get(resolved_symbol) if resolved_symbol else None
        if rth_open is not None and last_price is not None:
            is_above_open = last_price > rth_open
        is_above_vwap = vwap_val is not None and last_price is not None and last_price > vwap_val

        is_above_4h = profile["is_above_4h_ema"] if profile else None
        res_clusters = profile["resistance_clusters"] if profile else []
        sup_clusters = profile["support_clusters"] if profile else []
        prior_close = profile.get("prior_close") if profile else None
        htf_high = profile.get("htf_high") if profile else None
        has_market_data, is_market_green = self._market_state()
        if data_quality == "ok" and (not has_intraday or not has_4h or not has_market_data):
            data_quality = "partial"

        res_clusters_rel = _filter_clusters_relative(res_clusters, last_price, "resistance")
        sup_clusters_rel = _filter_clusters_relative(sup_clusters, last_price, "support")
        agg_for_levels = self._minute_agg if intraday_symbol_matches else MinuteBarAggregator()
        nearest_res = _nearest_level(last_price, res_clusters_rel, agg_for_levels, kind="resistance")
        nearest_sup = _nearest_level(last_price, sup_clusters_rel, agg_for_levels, kind="support")
        micro = _compute_micro_metrics(agg_bars, last_price)
        bars_window_5m = _build_bars_window_5m(agg_bars, limit=60)

        snapshot_symbol = profile["symbol"] if profile else (resolved_symbol or "")
        snapshot = {
            "symbol": snapshot_symbol,
            "as_of_ts_ms": now_ms,
            "as_of_et": datetime.now(ET_TZ).isoformat(),
            "status": status,
            "data_quality": data_quality,
            "has_4h_data": has_4h,
            "has_intraday_data": has_intraday,
            "has_market_data": has_market_data,
            "has_premarket_levels": bool(premarket_high_val is not None and premarket_low_val is not None),
            "has_opening_range": bool(or_high_val is not None and or_low_val is not None),
            "regime": {
                "is_above_4h_ema": is_above_4h,
                "is_above_open": is_above_open,
                "is_above_vwap": is_above_vwap,
                "is_market_green": is_market_green,
                "macd_regime": macd_regime,
                "macd_ready": len(agg_bars) >= MACD_MIN_BARS,
            },
            "volatility": {
                "intraday_range_pct": intraday_range_pct,
                "is_volatile_enough": is_volatile,
            },
            "volume": {"volume_multiple": vol_mult},
            "levels": {
                "resistance_clusters": res_clusters_rel,
                "support_clusters": sup_clusters_rel,
                "nearest_resistance": nearest_res,
                "nearest_support": nearest_sup,
                "in_resistance_zone": _in_resistance_zone(last_price, res_clusters),
                "distance_to_next_cluster_pct": _distance_to_next_cluster_pct(last_price, res_clusters),
            },
            "last_price": last_price,
            "vwap": vwap_val,
            "micro": micro,
            "session": {
                "premarket_high": premarket_high_val,
                "premarket_low": premarket_low_val,
                "opening_range_high": or_high_val,
                "opening_range_low": or_low_val,
                "open_price": session_open_val if session_open_val else None,
                "gap_pct": ((session_open_val - prior_close) / prior_close * 100) if prior_close and session_open_val else None,
            },
            "bars_window_5m": bars_window_5m,
        }
        derived = snapshot.get("derived", {}) or {}
        # current price fallback: last -> mid -> bid -> ask
        current_price = last_price
        quote = getattr(self, "_last_quote", None) if hasattr(self, "_last_quote") else None
        if current_price is None and isinstance(quote, dict):
            bid = quote.get("bid")
            ask = quote.get("ask")
            last = quote.get("last")
            if isinstance(last, (int, float)):
                current_price = float(last)
            else:
                mid = (bid + ask) / 2 if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) else None
                if mid is not None:
                    current_price = float(mid)
                elif isinstance(bid, (int, float)):
                    current_price = float(bid)
                elif isinstance(ask, (int, float)):
                    current_price = float(ask)

        def _pct(numer: Optional[float], denom: Optional[float]) -> Optional[float]:
            if numer is None or denom is None or denom == 0:
                return None
            return (numer - denom) / denom

        derived.update(
            {
                "distance_to_vwap_pct": _pct(current_price, vwap_val),
                "distance_to_premarket_high_pct": _pct(current_price, premarket_high_val),
                "distance_to_opening_range_high_pct": _pct(current_price, or_high_val),
                "distance_to_micro_resistance_15m_pct": _pct(current_price, micro.get("micro_resistance_15m") if isinstance(micro, dict) else None),
                "impulse_move_pct_session": _pct(premarket_high_val, premarket_low_val),
                "consolidation_range_pct": _pct(
                    (micro.get("micro_resistance_15m") if isinstance(micro, dict) else None),
                    (micro.get("micro_support_15m") if isinstance(micro, dict) else None),
                )
                if isinstance(micro, dict) and micro.get("micro_resistance_15m") and micro.get("micro_support_15m")
                else None,
            }
        )
        snapshot["derived"] = derived
        snapshot["levels_book"] = _build_levels_book(
            last_price=last_price,
            bars=agg_bars[-30:],
            res_clusters=res_clusters,
            sup_clusters=sup_clusters,
            micro=micro,
        )
        if snapshot_symbol:
            self._snapshot_cache[snapshot_symbol] = snapshot
        try:
            barish_keys = [k for k in snapshot.keys() if "bar" in k or "ohlc" in k or "candle" in k]
            logging.getLogger(__name__).debug(
                "Snapshot built keys=%s barish=%s bars_window_5m_len=%s",
                list(snapshot.keys()),
                barish_keys,
                len(bars_window_5m) if bars_window_5m else 0,
            )
        except Exception:
            pass
        return snapshot

    def _market_state(self) -> tuple[bool, Optional[bool]]:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if self._market_cache and (now_ms - self._market_cache[0] < 60_000):
            return self._market_cache[1], self._market_cache[2]
        if not self._rest:
            return False, None
        has_market = False
        is_green = None
        now_et = datetime.now(ET_TZ)
        try:
            for proxy in [MARKET_PROXY_SYMBOL, "QQQ"]:
                resp = self._rest.fetch_price_history(proxy, None, None, "1d")
                candles = resp.get("candles") or []
                completed = [c for c in candles if c.get("close") is not None]
                if len(completed) < 2:
                    continue
                prior_close = float(completed[-2].get("close"))
                last_close = float(completed[-1].get("close"))
                if prior_close <= 0:
                    continue
                baseline = prior_close
                open_start = datetime(now_et.year, now_et.month, now_et.day, 9, 30, tzinfo=ET_TZ)
                open_end = open_start + timedelta(minutes=1)
                if now_et.time() >= open_start.time():
                    bar_resp = self._rest.fetch_price_history(proxy, int(open_start.timestamp() * 1000), int(open_end.timestamp() * 1000), "1m")
                    bar_candles = bar_resp.get("candles") or []
                    open_bar = sorted(bar_candles, key=lambda c: c.get("datetime", 0))[0] if bar_candles else None
                    if open_bar and open_bar.get("open") is not None:
                        baseline = float(open_bar.get("open"))
                if baseline <= 0:
                    continue
                change_pct = (last_close - baseline) / baseline * 100
                is_green = change_pct > 0
                has_market = True
                break
        except Exception:
            has_market = False
            is_green = None
        self._market_cache = (now_ms, has_market, is_green)
        return has_market, is_green


def _filter_clusters_relative(clusters: list[dict], last_price: Optional[float], kind: str) -> list[dict]:
    if last_price is None:
        return clusters[:CLUSTER_CAP]
    filtered: list[dict] = []
    for c in clusters:
        mid = (c["price_zone_low"] + c["price_zone_high"]) / 2
        if kind == "resistance" and mid >= last_price:
            filtered.append(c)
        if kind == "support" and mid <= last_price:
            filtered.append(c)
    return filtered[:CLUSTER_CAP]


def _nearest_level(last_price: Optional[float], clusters: list[dict], agg: MinuteBarAggregator, kind: str) -> Optional[dict]:
    if last_price is None:
        return None
    candidates: list[dict] = []
    for c in clusters:
        mid = (c["price_zone_low"] + c["price_zone_high"]) / 2
        candidates.append({"price": mid, "source": f"cluster_{kind}", "distance_pct": (mid - last_price) / last_price * 100})
    v = agg.vwap()
    if v is not None:
        candidates.append({"price": v, "source": "vwap", "distance_pct": (v - last_price) / last_price * 100})
    if agg.or_high is not None:
        candidates.append({"price": agg.or_high, "source": "ORH", "distance_pct": (agg.or_high - last_price) / last_price * 100})
    if agg.or_low is not None:
        candidates.append({"price": agg.or_low, "source": "ORL", "distance_pct": (agg.or_low - last_price) / last_price * 100})
    if agg.premarket_high is not None:
        candidates.append({"price": agg.premarket_high, "source": "premarket_high", "distance_pct": (agg.premarket_high - last_price) / last_price * 100})
    if agg.premarket_low is not None:
        candidates.append({"price": agg.premarket_low, "source": "premarket_low", "distance_pct": (agg.premarket_low - last_price) / last_price * 100})
    if kind == "resistance":
        above = [c for c in candidates if c["price"] >= last_price]
        if not above:
            return None
        return sorted(above, key=lambda x: x["price"])[0]
    below = [c for c in candidates if c["price"] <= last_price]
    if not below:
        return None
    best = sorted(below, key=lambda x: x["price"], reverse=True)[0]
    rounded_price = round(best["price"], 3)
    best["price"] = rounded_price
    best["distance_pct"] = (rounded_price - last_price) / last_price * 100
    return best


def _in_resistance_zone(last_price: Optional[float], clusters: list[dict]) -> bool:
    if last_price is None:
        return False
    for c in clusters:
        if last_price >= c["price_zone_low"] and last_price <= c["price_zone_high"]:
            return True
    return False


def _distance_to_next_cluster_pct(last_price: Optional[float], clusters: list[dict]) -> Optional[float]:
    if last_price is None:
        return None
    mids = sorted([(c["price_zone_low"] + c["price_zone_high"]) / 2 for c in clusters if ((c["price_zone_low"] + c["price_zone_high"]) / 2) > last_price])
    if not mids:
        return None
    nxt = mids[0]
    return (nxt - last_price) / last_price * 100


def _build_levels_book(
    last_price: Optional[float],
    bars: list[OneMinuteBar],
    res_clusters: list[dict],
    sup_clusters: list[dict],
    micro: dict,
) -> list[dict]:
    if last_price is None or len(bars) < MICRO_WINDOW_15M:
        return []
    levels: list[dict] = []
    # Macro levels from clusters
    for c in res_clusters:
        levels.append(
            {
                "low": c["price_zone_low"],
                "high": c["price_zone_high"],
                "side": "resistance",
                "scope": "macro",
                "base_strength": c.get("strength_score", 0.0),
            }
        )
    for c in sup_clusters:
        levels.append(
            {
                "low": c["price_zone_low"],
                "high": c["price_zone_high"],
                "side": "support",
                "scope": "macro",
                "base_strength": c.get("strength_score", 0.0),
            }
        )
    # Micro levels (15m swings)
    micro_res = micro.get("micro_resistance_15m")
    micro_sup = micro.get("micro_support_15m")
    if micro_res is not None:
        levels.append(
            {
                "low": micro_res,
                "high": micro_res,
                "side": "resistance",
                "scope": "micro",
                "base_strength": 0.3,
            }
        )
    if micro_sup is not None:
        levels.append(
            {
                "low": micro_sup,
                "high": micro_sup,
                "side": "support",
                "scope": "micro",
                "base_strength": 0.3,
            }
        )
    if not levels:
        return []
    median_vol = float(pd.Series([b.volume for b in bars]).median()) if bars else 0.0
    touch_bars_cache: dict[int, OneMinuteBar] = {b.ts: b for b in bars}

    def distance_pct(level: dict) -> float:
        mid = (level["low"] + level["high"]) / 2
        return (mid - last_price) / last_price * 100

    def bar_volume_multiple(bar: OneMinuteBar) -> float:
        if median_vol <= 0:
            return 0.0
        return (bar.volume or 0.0) / median_vol

    enriched: list[dict] = []
    for lvl in levels:
        mid = (lvl["low"] + lvl["high"]) / 2
        side = lvl["side"]
        # cross behavior: resistance becomes support if price above
        if side == "resistance" and last_price > lvl["high"]:
            side = "support"
        lvl_touch_bars: list[OneMinuteBar] = []
        rejection_bars = 0
        clean_breaks = 0
        for b in bars:
            touches_zone = (b.high >= lvl["low"] and b.low <= lvl["high"])
            if touches_zone:
                lvl_touch_bars.append(b)
                upper_wick = b.high - max(b.open, b.close)
                lower_wick = min(b.open, b.close) - b.low
                body = abs(b.close - b.open)
                if side == "resistance" and upper_wick > body:
                    rejection_bars += 1
                if side == "support" and lower_wick > body:
                    rejection_bars += 1
            close_above = b.close > lvl["high"] * 1.005
            close_below = b.close < lvl["low"] * 0.995
            vol_mult_bar = bar_volume_multiple(b)
            if side == "resistance" and close_above and vol_mult_bar >= 2.0:
                clean_breaks += 1
            if side == "support" and close_below and vol_mult_bar >= 2.0:
                clean_breaks += 1
        touch_score = min(len(lvl_touch_bars) / 3.0, 1.0)
        rejection_score = min(rejection_bars / 3.0, 1.0)
        avg_touch_vol = (
            sum([b.volume for b in lvl_touch_bars]) / len(lvl_touch_bars) if lvl_touch_bars else 0.0
        )
        volume_score = 0.0
        if median_vol > 0 and avg_touch_vol > 0:
            volume_score = min(avg_touch_vol / median_vol, 2.0) / 2.0
        clean_break_penalty = min(clean_breaks / 2.0, 1.0)
        dist_pct = distance_pct(lvl)
        distance_decay = min(abs(dist_pct) / 10.0, 1.0)
        dynamic_influence = (
            lvl["base_strength"]
            + 0.15 * touch_score
            + 0.15 * rejection_score
            + 0.10 * volume_score
            - 0.20 * clean_break_penalty
            - 0.10 * distance_decay
        )
        dynamic_influence = max(0.0, min(1.0, dynamic_influence))
        enriched.append(
            {
                "low": lvl["low"],
                "high": lvl["high"],
                "side": side,
                "scope": lvl["scope"],
                "base_strength": lvl["base_strength"],
                "dynamic_influence": dynamic_influence,
                "distance_pct": dist_pct,
            }
        )
    enriched.sort(key=lambda d: (-d["dynamic_influence"], abs(d["distance_pct"])))
    return enriched


def _compute_micro_metrics(bars: list[OneMinuteBar], last_price: Optional[float]) -> dict:
    if not bars or last_price is None:
        return {
            "micro_resistance_15m": None,
            "micro_support_15m": None,
            "range_5m_pct": None,
            "range_15m_pct": None,
            "compression_ratio": None,
            "micro_state": None,
            "dist_to_micro_r_pct": None,
        }
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    micro_res_15 = None
    micro_sup_15 = None
    range_5m_pct = None
    range_15m_pct = None
    compression_ratio = None
    micro_state = None
    dist_to_micro_r_pct = None

    if len(bars) >= MICRO_WINDOW_15M:
        recent_highs = highs[-MICRO_WINDOW_15M:]
        recent_lows = lows[-MICRO_WINDOW_15M:]
        micro_res_15 = max(recent_highs)
        micro_sup_15 = min(recent_lows)
    if len(bars) >= MICRO_WINDOW_5M:
        recent_highs_5 = highs[-MICRO_WINDOW_5M:]
        recent_lows_5 = lows[-MICRO_WINDOW_5M:]
        if last_price:
            range_5m_pct = (max(recent_highs_5) - min(recent_lows_5)) / last_price * 100
    if len(bars) >= MICRO_WINDOW_15M and last_price:
        recent_highs_15 = highs[-MICRO_WINDOW_15M:]
        recent_lows_15 = lows[-MICRO_WINDOW_15M:]
        range_15m_pct = (max(recent_highs_15) - min(recent_lows_15)) / last_price * 100
    if range_5m_pct is not None and range_15m_pct is not None and range_15m_pct > 0:
        compression_ratio = range_5m_pct / range_15m_pct
        if compression_ratio <= 0.35:
            micro_state = "COIL"
        elif compression_ratio >= 0.60:
            micro_state = "EXPAND"
        else:
            micro_state = "NEUTRAL"
    if micro_res_15 is not None and last_price:
        dist_to_micro_r_pct = (micro_res_15 - last_price) / last_price * 100
    return {
        "micro_resistance_15m": micro_res_15,
        "micro_support_15m": micro_sup_15,
        "range_5m_pct": range_5m_pct,
        "range_15m_pct": range_15m_pct,
        "compression_ratio": compression_ratio,
        "micro_state": micro_state,
        "dist_to_micro_r_pct": dist_to_micro_r_pct,
    }


def _candles_to_df(candles: list[dict]) -> pd.DataFrame:
    rows = []
    for c in candles:
        dt = c.get("datetime")
        if dt is None:
            continue
        rows.append(
            {
                "ts_utc": datetime.fromtimestamp(int(dt) / 1000, tz=timezone.utc),
                "open": c.get("open"),
                "high": c.get("high"),
                "low": c.get("low"),
                "close": c.get("close"),
                "volume": c.get("volume") or 0,
                "is_extended": 0,
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("ts_utc").reset_index(drop=True)
    return df


def _build_bars_window_5m(bars_1m: list[OneMinuteBar], limit: int = 60) -> list[dict]:
    """Aggregate 1m bars into 5m bars, oldest->newest, capped to limit."""
    if not bars_1m:
        return []
    out: list[dict] = []
    current: dict | None = None
    current_bucket: Optional[int] = None
    for b in bars_1m:
        bucket = int(b.ts // 300)
        if current is None or bucket != current_bucket:
            if current:
                out.append(current)
            current_bucket = bucket
            current = {
                "ts_ms": int(b.ts * 1000),
                "o": b.open,
                "h": b.high,
                "l": b.low,
                "c": b.close,
                "v": b.volume,
            }
        else:
            current["h"] = max(current["h"], b.high)  # type: ignore[index]
            current["l"] = min(current["l"], b.low)  # type: ignore[index]
            current["c"] = b.close  # type: ignore[index]
            current["v"] = current["v"] + b.volume  # type: ignore[index]
    if current:
        out.append(current)
    if len(out) > limit:
        out = out[-limit:]
    return out
