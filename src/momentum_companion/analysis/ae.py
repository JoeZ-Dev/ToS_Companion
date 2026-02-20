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
                self._bars.append(self._current)
                self._volumes.append(self._current.volume)
                if len(self._volumes) > 300:
                    self._volumes = self._volumes[-300:]
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

    def reset_intraday(self) -> None:
        self._minute_agg = MinuteBarAggregator()
        self._snapshot_cache.clear()
        self._last_quote_ms = None
        self._market_cache = None
        self._seeded = False

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
            now_et = datetime.now(ET_TZ)
            start_et = datetime(now_et.year, now_et.month, now_et.day, 4, 0, tzinfo=ET_TZ)
            start_ms = int(start_et.timestamp() * 1000)
            end_ms = int(now_et.timestamp() * 1000)
            resp = self._rest.fetch_price_history(symbol, start_ms, end_ms, "1m")
            candles = resp.get("candles") or []
            seeded = 0
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
                self._minute_agg.session_high = b.high if self._minute_agg.session_high is None else max(self._minute_agg.session_high, b.high)
                self._minute_agg.session_low = b.low if self._minute_agg.session_low is None else min(self._minute_agg.session_low, b.low)
                seeded += 1
            if seeded == 0:
                return None
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
            self._seeded = True
            return self._build_snapshot()
        except Exception:
            return None

    def _build_snapshot(self) -> dict:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        quote_age = None
        if self._last_quote_ms is not None:
            quote_age = now_ms - self._last_quote_ms
        status = "ok"
        data_quality = "ok"
        has_intraday = bool(self._minute_agg.bars)
        has_4h = bool(self._profile_cache)
        has_market = False
        if quote_age is not None and quote_age > NO_DATA_IF_QUOTE_AGE_MS:
            data_quality = "no_data"
        elif quote_age is not None and quote_age > STALE_IF_QUOTE_AGE_MS:
            data_quality = "stale"
        if not has_intraday or not self._minute_agg.session_open:
            data_quality = "partial"

        last_price = self._minute_agg.bars[-1].close if self._minute_agg.bars else None
        vwap_val = self._minute_agg.vwap()
        intraday_range_pct = None
        is_volatile = None
        if self._minute_agg.session_high and self._minute_agg.session_low and self._minute_agg.session_open:
            intraday_range_pct = (
                (self._minute_agg.session_high - self._minute_agg.session_low) / self._minute_agg.session_open * 100
            )
            is_volatile = intraday_range_pct > VOLATILITY_THRESHOLD

        macd_regime = None
        if len(self._minute_agg.bars) >= MACD_MIN_BARS:
            closes = pd.Series([b.close for b in self._minute_agg.bars])
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
        baseline = self._minute_agg.rolling_volume_median()
        if baseline is not None and baseline > 0 and self._minute_agg.bars:
            vol_mult = self._minute_agg.bars[-1].volume / baseline

        is_above_open = None
        session_symbol = ""
        if self._profile_cache:
            session_symbol = next(iter(self._profile_cache.values())).get("symbol", "")
        rth_open = self._session_open_rth.get(session_symbol)
        if rth_open is not None and last_price is not None:
            is_above_open = last_price > rth_open
        is_above_vwap = vwap_val is not None and last_price is not None and last_price > vwap_val

        profile = next(iter(self._profile_cache.values()), None)
        is_above_4h = profile["is_above_4h_ema"] if profile else None
        res_clusters = profile["resistance_clusters"] if profile else []
        sup_clusters = profile["support_clusters"] if profile else []
        prior_close = profile.get("prior_close") if profile else None
        htf_high = profile.get("htf_high") if profile else None
        has_market_data, is_market_green = self._market_state()

        res_clusters_rel = _filter_clusters_relative(res_clusters, last_price, "resistance")
        sup_clusters_rel = _filter_clusters_relative(sup_clusters, last_price, "support")
        nearest_res = _nearest_level(last_price, res_clusters_rel, self._minute_agg, kind="resistance", fallback_high=htf_high)
        nearest_sup = _nearest_level(last_price, sup_clusters_rel, self._minute_agg, kind="support", fallback_high=None)

        snapshot = {
            "symbol": profile["symbol"] if profile else "",
            "as_of_ts_ms": now_ms,
            "as_of_et": datetime.now(ET_TZ).isoformat(),
            "status": status,
            "data_quality": data_quality,
            "has_4h_data": has_4h,
            "has_intraday_data": has_intraday,
            "has_market_data": has_market_data,
            "has_premarket_levels": bool(self._minute_agg.premarket_high is not None and self._minute_agg.premarket_low is not None),
            "has_opening_range": bool(self._minute_agg.or_high is not None and self._minute_agg.or_low is not None),
            "regime": {
                "is_above_4h_ema": is_above_4h,
                "is_above_open": is_above_open,
                "is_above_vwap": is_above_vwap,
                "is_market_green": is_market_green,
                "macd_regime": macd_regime,
                "macd_ready": len(self._minute_agg.bars) >= MACD_MIN_BARS,
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
            "session": {
                "premarket_high": self._minute_agg.premarket_high,
                "premarket_low": self._minute_agg.premarket_low,
                "opening_range_high": self._minute_agg.or_high,
                "opening_range_low": self._minute_agg.or_low,
                "gap_pct": ((self._minute_agg.session_open - prior_close) / prior_close * 100) if prior_close and self._minute_agg.session_open else None,
            },
        }
        self._snapshot_cache[profile["symbol"]] = snapshot if profile else snapshot
        return snapshot

    def _market_state(self) -> tuple[bool, Optional[bool]]:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if self._market_cache and (now_ms - self._market_cache[0] < 60_000):
            return self._market_cache[1], self._market_cache[2]
        if not self._rest:
            return False, None
        has_market = False
        is_green = None
        try:
            resp = self._rest.fetch_price_history("SPY", None, None, "1d")
            candles = resp.get("candles") or []
            if len(candles) >= 2:
                prior_close = float(candles[-2].get("close"))
                last_close = float(candles[-1].get("close"))
                if prior_close > 0:
                    change_pct = (last_close - prior_close) / prior_close * 100
                    is_green = change_pct > 0
                    has_market = True
        except Exception:
            has_market = False
            is_green = None
        self._market_cache = (now_ms, has_market, is_green)
        return has_market, is_green


def _filter_clusters_relative(clusters: list[dict], last_price: Optional[float], kind: str) -> list[dict]:
    if last_price is None:
        return clusters[:CLUSTER_CAP]
    filtered = []
    for c in clusters:
        mid = (c["price_zone_low"] + c["price_zone_high"]) / 2
        if kind == "resistance" and mid >= last_price:
            filtered.append(c)
        if kind == "support" and mid <= last_price:
            filtered.append(c)
    filtered = sorted(filtered, key=lambda c: (abs(((c["price_zone_low"] + c["price_zone_high"]) / 2) - last_price)))
    return filtered[:CLUSTER_CAP]


def _nearest_level(last_price: Optional[float], clusters: list[dict], agg: MinuteBarAggregator, kind: str, fallback_high: Optional[float]) -> Optional[dict]:
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
    if agg.session_high is not None:
        candidates.append({"price": agg.session_high, "source": "session_high", "distance_pct": (agg.session_high - last_price) / last_price * 100})
    if agg.session_low is not None:
        candidates.append({"price": agg.session_low, "source": "session_low", "distance_pct": (agg.session_low - last_price) / last_price * 100})
    if kind == "resistance":
        above = [c for c in candidates if c["price"] >= last_price]
        if not above and fallback_high is not None:
            above = [{"price": fallback_high, "source": "htf_high", "distance_pct": (fallback_high - last_price) / last_price * 100}]
        if not above:
            return None
        return sorted(above, key=lambda x: x["price"])[0]
    below = [c for c in candidates if c["price"] <= last_price]
    if not below:
        return None
    return sorted(below, key=lambda x: x["price"], reverse=True)[0]


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
