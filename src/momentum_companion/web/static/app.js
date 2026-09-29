(() => {
  const byId = (id) => document.getElementById(id);
  const fmtPrice = (value) =>
    value === null || value === undefined ? "--" : Number(value).toFixed(4);
  const fmtVolume = (value) =>
    value === null || value === undefined ? "--" : Number(value).toLocaleString();

  const state = {
    activeSymbol: null,
    symbols: {},
    socket: null,
    reconnectTimer: null,
    chartSymbol: null,
    chartRevision: null,
    chartFitSymbol: null,
    replayView: false,
    replaySnapshot: null,
    replaySessions: [],
    patternVisibility: {},
    patternTriggerHistory: {},
    patternOverlayRevision: null,
  };

  const EASTERN_TZ = "America/New_York";

  function formatEasternTime(timestamp) {
    const seconds = typeof timestamp === "number"
      ? timestamp
      : Number(timestamp?.timestamp ?? timestamp);
    if (!Number.isFinite(seconds)) return "";
    return new Intl.DateTimeFormat("en-US", {
      timeZone: EASTERN_TZ,
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
    }).format(new Date(seconds * 1000));
  }

  function formatEasternTick(timestamp) {
    const seconds = typeof timestamp === "number"
      ? timestamp
      : Number(timestamp?.timestamp ?? timestamp);
    if (!Number.isFinite(seconds)) return "";
    return new Intl.DateTimeFormat("en-US", {
      timeZone: EASTERN_TZ,
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    }).format(new Date(seconds * 1000));
  }

  const chart = LightweightCharts.createChart(byId("chart"), {
    autoSize: true,
    layout: {
      background: { color: "#0d1014" },
      textColor: "#8996a3",
    },
    grid: {
      vertLines: { color: "#171c22" },
      horzLines: { color: "#171c22" },
    },
    localization: {
      timeFormatter: formatEasternTime,
    },
    rightPriceScale: { borderColor: "#252c34" },
    timeScale: {
      borderColor: "#252c34",
      timeVisible: true,
      secondsVisible: true,
      tickMarkFormatter: formatEasternTick,
    },
  });

  const candleSeries = typeof chart.addCandlestickSeries === "function"
    ? chart.addCandlestickSeries({})
    : chart.addSeries(LightweightCharts.CandlestickSeries, {});
  const patternMarkerApi = typeof LightweightCharts.createSeriesMarkers === "function"
    ? LightweightCharts.createSeriesMarkers(candleSeries, [])
    : null;

  const addLineSeries = (options) =>
    typeof chart.addLineSeries === "function"
      ? chart.addLineSeries(options)
      : chart.addSeries(LightweightCharts.LineSeries, options);

  const addHistogramSeries = (options) =>
    typeof chart.addHistogramSeries === "function"
      ? chart.addHistogramSeries(options)
      : chart.addSeries(LightweightCharts.HistogramSeries, options);

  const volumeSeries = addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "",
    lastValueVisible: false,
    priceLineVisible: false,
  });
  chart.priceScale("").applyOptions({
    scaleMargins: { top: 0.82, bottom: 0 },
    visible: false,
  });

  const vwapSeries = addLineSeries({
    color: "#b455ff",
    lineWidth: 2,
    lastValueVisible: false,
    priceLineVisible: false,
  });
  const ema9Series = addLineSeries({
    color: "#f5c542",
    lineWidth: 1,
    lastValueVisible: false,
    priceLineVisible: false,
  });
  const ema20Series = addLineSeries({
    color: "#4aa3ff",
    lineWidth: 1,
    lastValueVisible: false,
    priceLineVisible: false,
  });

  let structuralPriceLines = [];
  const patternOverlaySeries = new Map();

  function normalizeBar(bar) {
    return {
      time: Number(bar.time ?? bar.ts),
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
      volume: Number(bar.volume || 0),
    };
  }

  function emaPoints(bars, length) {
    const alpha = 2 / (length + 1);
    let ema = null;
    return bars.map((bar) => {
      ema = ema === null ? bar.close : alpha * bar.close + (1 - alpha) * ema;
      return { time: bar.time, value: ema };
    });
  }

  function vwapPoints(symbolState) {
    return (symbolState?.vwap_points || []).filter(
      (point) => Number.isFinite(point.time) && Number.isFinite(point.value)
    );
  }

  function setStructuralLines(snapshot) {
    for (const line of structuralPriceLines) {
      try {
        candleSeries.removePriceLine(line);
      } catch (_error) {}
    }
    structuralPriceLines = [];

    const session = snapshot?.session || {};
    const levels = snapshot?.levels || {};
    const candidates = [
      ["PMH", session.premarket_high],
      ["PML", session.premarket_low],
      ["ORH", session.opening_range_high],
      ["ORL", session.opening_range_low],
      ["R", levels.nearest_resistance?.price],
      ["S", levels.nearest_support?.price],
    ];

    const seen = new Set();
    for (const [title, rawPrice] of candidates) {
      const price = Number(rawPrice);
      if (!Number.isFinite(price)) continue;
      const key = price.toFixed(6);
      if (seen.has(key)) continue;
      seen.add(key);
      try {
        structuralPriceLines.push(
          candleSeries.createPriceLine({
            price,
            title,
            axisLabelVisible: true,
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle?.Dashed ?? 2,
          })
        );
      } catch (_error) {}
    }
  }

  const PATTERN_MARKER_SERIES_CONFIG = Object.freeze({
    position: "aboveBar",
    shape: "arrowDown",
    detectors: Object.freeze({
      ASCENDING_TRIANGLE: Object.freeze({
        color: "#46c2ff",
        name: "Ascending Triangle",
      }),
      MICRO_PULLBACK: Object.freeze({
        color: "#f2b84b",
        name: "Micro Pullback",
      }),
      LOCAL_RESISTANCE_BREAKOUT: Object.freeze({
        color: "#db7cff",
        name: "Local Resistance Breakout",
      }),
      TIGHT_CONSOLIDATION_BREAKOUT: Object.freeze({
        color: "#5ed39a",
        name: "Tight Consolidation Breakout",
      }),
    }),
    fallbackPalette: Object.freeze([
      "#64b5f6",
      "#ff8a80",
      "#b39ddb",
      "#80cbc4",
      "#ffd180",
    ]),
  });

  const PATTERN_MARKER_SHARED_HELP =
    "Markers point to the candle they annotate. A downward-pointing marker does not mean sell or bearish.";

  function patternMarkerDefinition(patternType) {
    const normalized = String(patternType || "PATTERN").toUpperCase();
    const configured = PATTERN_MARKER_SERIES_CONFIG.detectors[normalized];
    if (configured) {
      return {
        patternType: normalized,
        detectorName: configured.name,
        color: configured.color,
        eventType: "detector transition",
      };
    }
    let hash = 0;
    for (const character of normalized) {
      hash = ((hash << 5) - hash + character.charCodeAt(0)) | 0;
    }
    const detectorName = normalized
      .toLowerCase()
      .split("_")
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
    return {
      patternType: normalized,
      detectorName,
      color: PATTERN_MARKER_SERIES_CONFIG.fallbackPalette[
        Math.abs(hash) % PATTERN_MARKER_SERIES_CONFIG.fallbackPalette.length
      ],
      eventType: "detector transition",
    };
  }

  function patternColor(patternType) {
    return patternMarkerDefinition(patternType).color;
  }

  function patternMarkerTooltip(patternType) {
    const marker = patternMarkerDefinition(patternType);
    return [
      `${marker.detectorName}: ${marker.color} identifies transitions emitted by this detector.`,
      "Event type: detector transition (BREAKOUT or CONTINUATION), not an opportunity-start, repeated-signal, or other-event marker.",
      PATTERN_MARKER_SHARED_HELP,
      "Production cooldown grouping treats the first eligible candidate as the opportunity start and attaches candidates suppressed by the existing cooldown to that opportunity as repeated signals; grouping does not change this marker's color, position, or behavior.",
      `Click to toggle ${marker.detectorName} geometry and trigger markers.`,
    ].join(" ");
  }

  function patternLineStyle(role) {
    const normalized = String(role || "").toLowerCase();
    if (normalized.includes("support") || normalized.includes("pullback")) {
      return LightweightCharts.LineStyle?.Dashed ?? 2;
    }
    if (normalized.includes("range") || normalized.includes("recovery")) {
      return LightweightCharts.LineStyle?.Dotted ?? 1;
    }
    return LightweightCharts.LineStyle?.Solid ?? 0;
  }

  function patternOverlayDescriptors(patterns, visibility = {}) {
    const lines = [];
    const triggers = [];
    for (const pattern of Array.isArray(patterns) ? patterns : []) {
      const patternType = String(pattern?.pattern_type || "PATTERN").toUpperCase();
      if (visibility[patternType] === false) continue;
      const patternId = String(pattern?.id || `${patternType}:${pattern?.started_at || "unknown"}`);
      const color = patternColor(patternType);
      for (const [index, line] of (pattern?.lines || []).entries()) {
        const startTime = Number(line?.start?.time);
        const endTime = Number(line?.end?.time);
        const startPrice = Number(line?.start?.price);
        const endPrice = Number(line?.end?.price);
        if (![startTime, endTime, startPrice, endPrice].every(Number.isFinite)) continue;
        if (startTime === endTime) continue;
        const points = [
          { time: startTime, value: startPrice },
          { time: endTime, value: endPrice },
        ].sort((first, second) => first.time - second.time);
        lines.push({
          key: `${patternId}:${line.role || "line"}:${index}`,
          patternId,
          patternType,
          role: String(line.role || "line"),
          color,
          lineStyle: patternLineStyle(line.role),
          points,
        });
      }

      const recoveryPrice = Number(pattern?.evidence?.recovery_pivot);
      const recoveryTime = Number(pattern?.evidence?.recovery_pivot_time);
      const updatedAt = Number(pattern?.updated_at);
      if (
        patternType === "MICRO_PULLBACK"
        && [recoveryPrice, recoveryTime, updatedAt].every(Number.isFinite)
        && updatedAt > recoveryTime
      ) {
        lines.push({
          key: `${patternId}:recovery_pivot`,
          patternId,
          patternType,
          role: "recovery_pivot",
          color,
          lineStyle: patternLineStyle("recovery"),
          points: [
            { time: recoveryTime, value: recoveryPrice },
            { time: updatedAt, value: recoveryPrice },
          ],
        });
      }

      const patternState = String(pattern?.state || "").toUpperCase();
      if (["BREAKOUT", "CONTINUATION"].includes(patternState) && Number.isFinite(updatedAt)) {
        triggers.push({
          key: `${patternId}:${patternState}:${updatedAt}`,
          patternId,
          patternType,
          state: patternState,
          time: updatedAt,
          color,
        });
      }
    }
    return { lines, triggers };
  }

  function patternShortName(patternType) {
    return String(patternType || "P")
      .split("_")
      .filter(Boolean)
      .map((part) => part.charAt(0))
      .join("")
      .slice(0, 4);
  }

  function rememberPatternTriggers(chartKey, triggers) {
    const existing = state.patternTriggerHistory[chartKey] || [];
    const byKey = new Map(existing.map((marker) => [marker.key, marker]));
    for (const trigger of triggers) byKey.set(trigger.key, trigger);
    const retained = [...byKey.values()]
      .sort((first, second) => first.time - second.time)
      .slice(-50);
    state.patternTriggerHistory[chartKey] = retained;
    return retained;
  }

  function setPatternMarkers(markers) {
    const chartMarkers = markers.map((marker) => ({
      time: marker.time,
      position: PATTERN_MARKER_SERIES_CONFIG.position,
      shape: PATTERN_MARKER_SERIES_CONFIG.shape,
      color: marker.color,
      // Keep trigger markers compact. Pattern type/state remain available in
      // the Patterns panel and filter legend, while text here obscures price
      // action when several detectors trigger close together.
      text: "",
      id: marker.key,
    }));
    if (patternMarkerApi) {
      patternMarkerApi.setMarkers(chartMarkers);
    } else if (typeof candleSeries.setMarkers === "function") {
      candleSeries.setMarkers(chartMarkers);
    }
  }

  function renderPatternOverlayFilters(patterns, chartKey) {
    const host = byId("pattern-overlay-filters");
    const types = new Set(
      (Array.isArray(patterns) ? patterns : [])
        .map((pattern) => String(pattern?.pattern_type || "").toUpperCase())
        .filter(Boolean)
    );
    for (const marker of state.patternTriggerHistory[chartKey] || []) {
      types.add(marker.patternType);
    }
    host.innerHTML = [...types].sort().map((patternType) => {
      const visible = state.patternVisibility[patternType] !== false;
      const marker = patternMarkerDefinition(patternType);
      const tooltip = patternMarkerTooltip(patternType);
      return `<button type="button" class="pattern-filter" data-pattern-type="${escapeHtml(patternType)}" aria-pressed="${visible}" aria-label="${escapeHtml(tooltip)}" style="--pattern-color:${marker.color}" title="${escapeHtml(tooltip)}">${escapeHtml(patternShortName(patternType))}</button>`;
    }).join("");
  }

  function setPatternOverlays(patterns, chartKey) {
    const allDescriptors = patternOverlayDescriptors(patterns, {});
    const triggerHistory = rememberPatternTriggers(chartKey, allDescriptors.triggers);
    renderPatternOverlayFilters(patterns, chartKey);
    const descriptors = patternOverlayDescriptors(patterns, state.patternVisibility);
    const visibleMarkers = triggerHistory.filter(
      (marker) => state.patternVisibility[marker.patternType] !== false
    );
    const revision = JSON.stringify({
      chartKey,
      lines: descriptors.lines,
      markers: visibleMarkers,
      visibility: state.patternVisibility,
    });
    if (revision === state.patternOverlayRevision) return;

    const visibleRange = chart.timeScale().getVisibleLogicalRange?.() || null;
    const activeKeys = new Set(descriptors.lines.map((descriptor) => descriptor.key));
    for (const [key, series] of patternOverlaySeries.entries()) {
      if (activeKeys.has(key)) continue;
      try {
        chart.removeSeries(series);
      } catch (_error) {}
      patternOverlaySeries.delete(key);
    }
    for (const descriptor of descriptors.lines) {
      let series = patternOverlaySeries.get(descriptor.key);
      if (!series) {
        series = addLineSeries({
          color: descriptor.color,
          lineWidth: 2,
          lineStyle: descriptor.lineStyle,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: true,
          // Keep pattern geometry visually lightweight. Lightweight Charts
          // renders non-empty series titles as in-pane labels, which can
          // obscure candles when several detector levels are close together.
          title: "",
        });
        patternOverlaySeries.set(descriptor.key, series);
      }
      series.setData(descriptor.points);
    }
    setPatternMarkers(visibleMarkers);
    if (visibleRange && typeof chart.timeScale().setVisibleLogicalRange === "function") {
      chart.timeScale().setVisibleLogicalRange(visibleRange);
    }
    state.patternOverlayRevision = revision;
  }

  function mergedBars(symbolState) {
    const byTime = new Map();
    for (const source of [symbolState?.history_bars || [], symbolState?.bars_10s || []]) {
      for (const raw of source) {
        if (!raw || (raw.time === undefined && raw.ts === undefined)) continue;
        const bar = normalizeBar(raw);
        if (
          !Number.isFinite(bar.time) ||
          !Number.isFinite(bar.open) ||
          !Number.isFinite(bar.high) ||
          !Number.isFinite(bar.low) ||
          !Number.isFinite(bar.close)
        ) {
          continue;
        }
        // Live 10-second evidence is processed after REST history, so if an
        // exact timestamp collides it wins deterministically.
        byTime.set(bar.time, bar);
      }
    }
    return [...byTime.values()].sort((a, b) => a.time - b.time);
  }

  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  function fmtMaybePrice(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(2) : "--";
  }

  function fmtMaybePct(value, digits = 2) {
    const number = Number(value);
    return Number.isFinite(number) ? `${number.toFixed(digits)}%` : "--";
  }

  function distanceFromLast(price, last) {
    const p = Number(price);
    const l = Number(last);
    if (!Number.isFinite(p) || !Number.isFinite(l) || l === 0) return null;
    return ((p - l) / l) * 100;
  }

  function setTab(name) {
    const wasReplay = state.replayView;
    state.replayView = name === "replay";
    document.querySelectorAll(".tab-button").forEach((button) => {
      button.classList.toggle("active", button.dataset.tab === name);
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.id === `tab-${name}`);
    });
    if (state.replayView) {
      void refreshReplayState();
    } else if (wasReplay) {
      state.chartSymbol = null;
      state.chartRevision = null;
      state.chartFitSymbol = null;
      renderActive({ chartChanged: true });
    }
  }

  function recordingEventCount(counts) {
    if (!counts || typeof counts !== "object") return 0;
    return Object.values(counts).reduce((total, value) => total + (Number(value) || 0), 0);
  }

  function renderRecorderState(recorderState) {
    const recorder = recorderState || { active: false };
    const active = Boolean(recorder.active);
    const symbols = Array.isArray(recorder.symbols) ? recorder.symbols : [];
    const activeSymbols = new Set(Array.isArray(recorder.active_symbols) ? recorder.active_symbols : []);
    const lifecycle = recorder.symbol_lifecycle || {};
    const counts = recorder.counts || {};
    const pre7Seeds = recorder.pre7_seeds || {};

    byId("recording-status").textContent = active ? "ACTIVE" : "INACTIVE";
    byId("recording-status").classList.toggle("active", active);
    byId("recording-status").classList.toggle("inactive", !active);
    byId("record-start").disabled = active;
    byId("record-stop").disabled = !active;
    byId("record-add-symbol").disabled = !active;
    byId("record-add-active").disabled = !active;
    byId("recording-count").textContent = String(activeSymbols.size);
    byId("recording-session-dir").textContent = recorder.session_dir || "--";
    byId("recording-cutoff").textContent = recorder.cutoff_et ? `${recorder.cutoff_et} ET` : "3:00 PM ET";

    byId("recording-symbol-list").innerHTML = symbols.length
      ? symbols.map((symbol) => {
          const isActive = activeSymbols.has(symbol);
          const periods = lifecycle[symbol]?.periods || [];
          const latest = periods[periods.length - 1] || {};
          const count = recordingEventCount(counts[symbol]);
          const pre7 = pre7Seeds[symbol] || null;
          return `
            <div class="recording-symbol-row">
              <div class="recording-symbol-main">
                <strong>${escapeHtml(symbol)}</strong>
                <span class="recording-symbol-state ${isActive ? "active" : "stopped"}">${isActive ? "RECORDING" : "STOPPED"}</span>
              </div>
              <div class="recording-symbol-detail">
                <span>${count.toLocaleString()} events</span>
                <span>${isActive ? "since" : "last interval"} ${escapeHtml(latest.started_at_et ? new Date(latest.started_at_et).toLocaleTimeString("en-US", {timeZone: EASTERN_TZ, hour: "numeric", minute: "2-digit"}) : "--")}</span>
                <span>${pre7 ? `PRE7 ${Number(pre7.vwap).toFixed(4)} / ${Number(pre7.volume).toLocaleString()}` : "PRE7 not set"}</span>
              </div>
              <button class="recording-toggle" type="button" data-record-symbol="${escapeHtml(symbol)}" data-record-action="${isActive ? "remove" : "add"}" ${active ? "" : "disabled"}>
                ${isActive ? "Remove" : "Resume"}
              </button>
            </div>
          `;
        }).join("")
      : '<div class="muted-copy">Session is active. Add a ticker to begin collecting data.</div>';

    document.querySelectorAll("[data-record-symbol]").forEach((button) => {
      button.addEventListener("click", () => {
        const symbol = button.dataset.recordSymbol;
        if (button.dataset.recordAction === "remove") {
          void removeRecordingSymbol(symbol);
        } else {
          void addRecordingSymbol(symbol);
        }
      });
    });
  }

  function setRecordingMessage(message, error = false) {
    const host = byId("recording-message");
    host.textContent = message;
    host.classList.toggle("error", error);
  }

  function renderMarketState(snapshot) {
    const host = byId("market-state");
    if (!snapshot) {
      host.innerHTML = '<span class="muted-copy">No analysis snapshot yet.</span>';
      return;
    }
    const regime = snapshot.regime || {};
    const volatility = snapshot.volatility || {};
    const volume = snapshot.volume || {};
    const chips = [
      [regime.is_above_vwap ? "Above VWAP" : "Below VWAP", regime.is_above_vwap ? "good" : "bad"],
      [regime.is_above_4h_ema ? "Above 4H EMA" : "Below 4H EMA", regime.is_above_4h_ema ? "good" : "bad"],
      [regime.is_market_green ? "Market Green" : "Market Red", regime.is_market_green ? "good" : "bad"],
      [`MACD ${String(regime.macd_regime || "unknown").toUpperCase()}`, regime.macd_regime === "bullish" ? "good" : regime.macd_regime === "bearish" ? "bad" : ""],
      [regime.macd_ready ? "MACD Ready" : "MACD Warming", regime.macd_ready ? "good" : "warn"],
      [volatility.is_volatile_enough ? "Volatile" : "Low Volatility", volatility.is_volatile_enough ? "warn" : ""],
      [`Volume ${Number.isFinite(Number(volume.volume_multiple)) ? Number(volume.volume_multiple).toFixed(2) + "x" : "--"}`, Number(volume.volume_multiple) >= 1 ? "good" : "warn"],
    ];
    host.innerHTML = chips
      .map(([label, tone]) => `<span class="chip ${tone}">${escapeHtml(label)}</span>`)
      .join("");
  }

  function renderMetrics(snapshot) {
    const host = byId("key-metrics");
    if (!snapshot) {
      host.innerHTML = '<div class="muted-copy">No metrics available.</div>';
      return;
    }
    const rows = [
      ["Last", fmtMaybePrice(snapshot.last_price)],
      ["VWAP", fmtMaybePrice(snapshot.vwap)],
      ["Intraday Range", fmtMaybePct(snapshot.volatility?.intraday_range_pct)],
      ["Volume Multiple", Number.isFinite(Number(snapshot.volume?.volume_multiple)) ? Number(snapshot.volume.volume_multiple).toFixed(2) + "x" : "--"],
      ["Shares Out.", Number.isFinite(Number(snapshot.fundamentals?.shares_outstanding)) ? fmtVolume(snapshot.fundamentals.shares_outstanding) : "--"],
      ["Float Mkt Cap", Number.isFinite(Number(snapshot.fundamentals?.market_cap_float)) ? fmtVolume(snapshot.fundamentals.market_cap_float) : "--"],
      ["Short % Float", Number.isFinite(Number(snapshot.fundamentals?.short_interest_to_float)) ? Number(snapshot.fundamentals.short_interest_to_float).toFixed(2) + "%" : "--"],
      ["Micro State", snapshot.micro?.micro_state || "--"],
      ["MACD", snapshot.regime?.macd_regime || "--"],
      ["As of", snapshot.as_of_et ? new Date(snapshot.as_of_et).toLocaleTimeString("en-US", { timeZone: EASTERN_TZ, hour: "numeric", minute: "2-digit", second: "2-digit" }) : "--"],
      ["Data Quality", snapshot.data_quality || "--"],
    ];
    host.innerHTML = rows.map(([label, value]) =>
      `<div class="metric"><span class="metric-label">${escapeHtml(label)}</span><span class="metric-value">${escapeHtml(value)}</span></div>`
    ).join("");
  }

  function renderLevels(snapshot) {
    const host = byId("key-levels");
    if (!snapshot) {
      host.innerHTML = '<tr><td colspan="3" class="muted-copy">No levels available.</td></tr>';
      return;
    }

    const last = Number(snapshot.last_price);
    const rawRows = [
      ["ORL", snapshot.session?.opening_range_low],
      ["Micro R", snapshot.micro?.micro_resistance_15m],
      ["Micro S", snapshot.micro?.micro_support_15m],
      ["VWAP", snapshot.vwap],
      ["Nearest R", snapshot.levels?.nearest_resistance?.price],
      ["Nearest S", snapshot.levels?.nearest_support?.price],
      ["PMH", snapshot.session?.premarket_high],
      ["PML", snapshot.session?.premarket_low],
      ["ORH", snapshot.session?.opening_range_high],
    ]
      .filter(([, value]) => Number.isFinite(Number(value)))
      .map(([name, value]) => ({
        names: [name],
        price: Number(value),
        distance: distanceFromLast(value, last),
      }))
      .sort((a, b) => Math.abs(a.distance ?? 9999) - Math.abs(b.distance ?? 9999));

    // Collapse display-equivalent levels so VWAP/support or overlapping
    // structural references do not consume multiple rows.
    const merged = [];
    const mergeTolerance = Number.isFinite(last) && last > 0
      ? Math.max(0.01, last * 0.0015)
      : 0.01;
    for (const row of rawRows) {
      const existing = merged.find((candidate) =>
        Math.abs(candidate.price - row.price) <= mergeTolerance
      );
      if (existing) {
        existing.names.push(...row.names);
        continue;
      }
      merged.push(row);
    }

    // Analysis view is intentionally proximity-focused. Keep distant session
    // levels on the chart/Raw view unless there are too few nearby levels.
    const nearby = merged.filter((row) =>
      row.distance !== null && Math.abs(row.distance) <= 35
    );
    const displayRows = [...nearby];
    for (const row of merged) {
      if (displayRows.length >= 5) break;
      if (!displayRows.includes(row)) displayRows.push(row);
    }

    host.innerHTML = displayRows.slice(0, 5).map((row) => {
      const distance = row.distance;
      const className = distance === null
        ? "distance-flat"
        : distance > 0
          ? "distance-up"
          : distance < 0
            ? "distance-down"
            : "distance-flat";
      const distanceText = distance === null
        ? "--"
        : `${distance >= 0 ? "+" : ""}${distance.toFixed(2)}%`;
      const label = row.names.join(" / ");
      return `<tr><td class="level-name">${escapeHtml(label)}</td><td>${escapeHtml(fmtMaybePrice(row.price))}</td><td class="${className}">${escapeHtml(distanceText)}</td></tr>`;
    }).join("");
  }

  function humanizePatternName(value) {
    return String(value || "Pattern")
      .toLowerCase()
      .split("_")
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  }

  function patternEvidenceSummary(pattern) {
    const evidence = pattern?.evidence || {};
    if (pattern?.pattern_type === "MICRO_PULLBACK") {
      const impulse = Number(evidence.impulse_pct);
      const retrace = Number(evidence.retracement_pct);
      const duration = Number(evidence.duration_sec);
      const parts = [];
      if (Number.isFinite(impulse)) parts.push(`impulse ${(impulse * 100).toFixed(1)}%`);
      if (Number.isFinite(retrace)) parts.push(`retracement ${(retrace * 100).toFixed(1)}%`);
      if (Number.isFinite(duration)) parts.push(`${Math.round(duration)}s`);
      return parts.join(" · ");
    }
    if (pattern?.pattern_type === "ASCENDING_TRIANGLE") {
      const touches = Number(evidence.resistance_touches);
      const lows = Number(evidence.higher_lows);
      const compression = Number(evidence.compression_pct);
      const parts = [];
      if (Number.isFinite(touches)) parts.push(`${touches} resistance touches`);
      if (Number.isFinite(lows)) parts.push(`${lows} higher lows`);
      if (Number.isFinite(compression)) parts.push(`${compression.toFixed(0)}% compression`);
      return parts.join(" · ");
    }
    const keys = Object.keys(evidence).slice(0, 3);
    return keys.map((key) => {
      const value = evidence[key];
      const numeric = Number(value);
      const display = Number.isFinite(numeric)
        ? numeric.toLocaleString("en-US", { maximumFractionDigits: 4, useGrouping: false })
        : String(value);
      return `${key.replaceAll("_", " ")}: ${display}`;
    }).join(" · ");
  }

  function patternTone(patternState) {
    const value = String(patternState || "").toUpperCase();
    if (["BREAKOUT", "CONTINUATION", "VALID"].includes(value)) return "good";
    if (value === "INVALIDATED") return "bad";
    return "warn";
  }

  function patternDetailText(pattern) {
    const started = Number(pattern?.started_at);
    const updated = Number(pattern?.updated_at);
    const details = [
      `Pattern: ${humanizePatternName(pattern?.pattern_type)}`,
      `State: ${String(pattern?.state || "--")}`,
      `Started: ${Number.isFinite(started) ? formatEasternTime(started) : "unavailable"}`,
      `Updated: ${Number.isFinite(updated) ? formatEasternTime(updated) : "unavailable"}`,
      `Evidence: ${JSON.stringify(pattern?.evidence || {})}`,
    ];
    return details.join("\n");
  }

  function renderPatterns(symbolState) {
    const patterns = Array.isArray(symbolState?.pattern_observations)
      ? symbolState.pattern_observations
      : [];
    byId("pattern-count").textContent = String(patterns.length);
    byId("pattern-list").innerHTML = patterns.length
      ? patterns.map((pattern) => `
          <div class="pattern-row" title="${escapeHtml(patternDetailText(pattern))}">
            <span class="pattern-name">${escapeHtml(humanizePatternName(pattern.pattern_type))}</span>
            <span class="chip pattern-state ${patternTone(pattern.state)}">${escapeHtml(pattern.state || "--")}</span>
            <span class="pattern-evidence">${escapeHtml(patternEvidenceSummary(pattern) || "detected structure")}</span>
          </div>
        `).join("")
      : '<div class="muted-copy">No active patterns detected yet.</div>';
    byId("pattern-raw").textContent = patterns.length
      ? JSON.stringify(patterns, null, 2)
      : "No pattern observations yet.";
  }

  function setupSourceBadge(setup) {
    const pattern = setup?.source_pattern || setup?.pattern_type;
    if (pattern) {
      return `<span class="setup-source pattern-source">PATTERN: ${escapeHtml(humanizePatternName(pattern))}</span>`;
    }
    return '<span class="setup-source llm-source">LLM</span>';
  }

  function renderSetupCard(setup, compact = false) {
    if (!setup || typeof setup !== "object") return "";
    const stateName = String(setup.setup_state || "WATCH").toLowerCase();
    const warning = setup.tape_warning && setup.tape_warning !== "NONE"
      ? `<span class="tape-warning">${escapeHtml(String(setup.tape_warning).replaceAll("_", " "))}</span>`
      : "";
    const primaryPriceLabel = String(setup.setup_state || "WATCH").toUpperCase() === "WATCH"
      ? "Trigger"
      : "Entry";
    return `
      <article class="setup-card ${compact ? "compact" : ""}">
        <div class="setup-title-row">
          <div class="setup-title">${escapeHtml(setup.name || "Unnamed setup")}</div>
          <div class="setup-badges">
            ${setupSourceBadge(setup)}
            <span class="setup-state ${escapeHtml(stateName)}">${escapeHtml(setup.setup_state || "WATCH")}</span>
            ${warning}
          </div>
        </div>
        <div class="setup-grid">
          <div class="setup-field"><span>${escapeHtml(primaryPriceLabel)}</span><strong>${escapeHtml(fmtMaybePrice(setup.entry_trigger_price))}</strong></div>
          <div class="setup-field"><span>Stop</span><strong>${escapeHtml(fmtMaybePrice(setup.stop_price))}</strong></div>
          <div class="setup-field"><span>Target</span><strong>${escapeHtml(fmtMaybePrice(setup.target_price))}</strong></div>
          <div class="setup-field"><span>R/R</span><strong>${escapeHtml(Number.isFinite(Number(setup.rr_to_target1)) ? Number(setup.rr_to_target1).toFixed(2) + ":1" : "--")}</strong></div>
          <div class="setup-field"><span>Move</span><strong>${escapeHtml(fmtMaybePct(setup.move_pct_to_target1))}</strong></div>
          <div class="setup-field"><span>Extension</span><strong>${escapeHtml(fmtMaybePrice(setup.extension_target))}</strong></div>
        </div>
        <div class="setup-trigger"><strong>Trigger:</strong> ${escapeHtml(setup.trigger_condition || "--")}</div>
        <div class="setup-confirmation"><strong>Confirmation:</strong> ${escapeHtml(setup.confirmation_requirements || "--")}</div>
        <div class="setup-extension"><strong>Extension:</strong> ${escapeHtml(setup.extension_notes || "--")}</div>
      </article>
    `;
  }

  function renderSetupPreviewRow(setup) {
    if (!setup || typeof setup !== "object") return "";
    const setupState = String(setup.setup_state || "WATCH").toUpperCase();
    const stateName = setupState.toLowerCase();
    const primaryPriceLabel = setupState === "WATCH" ? "Trigger" : "Entry";
    return `
      <button class="setup-preview-row" type="button" data-open-setups="true">
        <span class="setup-preview-name">${escapeHtml(setup.name || "Unnamed setup")}</span>
        ${setupSourceBadge(setup)}
        <span class="setup-state ${escapeHtml(stateName)}">${escapeHtml(setupState)}</span>
        <span class="setup-preview-stat"><small>${escapeHtml(primaryPriceLabel)}</small><strong>${escapeHtml(fmtMaybePrice(setup.entry_trigger_price))}</strong></span>
        <span class="setup-preview-stat"><small>Target</small><strong>${escapeHtml(fmtMaybePrice(setup.target_price))}</strong></span>
        <span class="setup-preview-stat"><small>R/R</small><strong>${escapeHtml(Number.isFinite(Number(setup.rr_to_target1)) ? Number(setup.rr_to_target1).toFixed(2) + ":1" : "--")}</strong></span>
      </button>
    `;
  }

  function renderSetups(output) {
    const setups = Array.isArray(output?.setups) ? output.setups : [];
    byId("setup-count").textContent = String(setups.length);
    byId("setup-preview").innerHTML = setups.length
      ? setups.slice(0, 2).map(renderSetupPreviewRow).join("")
      : '<div class="muted-copy">Run LLM analysis to populate setups.</div>';
    byId("setup-list").innerHTML = setups.length
      ? setups.map((setup) => renderSetupCard(setup, false)).join("")
      : '<div class="muted-copy">Run LLM analysis to populate setups.</div>';
    document.querySelectorAll("[data-open-setups='true']").forEach((button) => {
      button.addEventListener("click", () => setTab("setups"));
    });
  }

  function quoteFreshness(symbolState) {
    const receivedAt = Number(symbolState?.quote?._client_received_at_ms);
    if (!Number.isFinite(receivedAt)) {
      return { status: "NO DATA", ageSeconds: null };
    }
    const ageMs = Math.max(0, Date.now() - receivedAt);
    return {
      status: ageMs < 1000 ? "LIVE" : (ageMs < 3000 ? "DELAYED" : "STALE"),
      ageSeconds: ageMs / 1000,
    };
  }

  function renderFreshness(symbolState) {
    const host = byId("quote-freshness");
    const freshness = quoteFreshness(symbolState);
    host.classList.remove("live", "delayed", "stale", "no-data", "replay");
    if (freshness.status === "LIVE") {
      host.classList.add("live");
      host.textContent = "LIVE";
    } else if (freshness.status === "DELAYED") {
      host.classList.add("delayed");
      host.textContent = `DELAY ${freshness.ageSeconds.toFixed(1)}s`;
    } else if (freshness.status === "STALE") {
      host.classList.add("stale");
      host.textContent = `STALE ${freshness.ageSeconds.toFixed(1)}s`;
    } else {
      host.classList.add("no-data");
      host.textContent = "NO DATA";
    }
  }

  function renderAnalysisView(symbolState) {
    const snapshot = symbolState?.ae_snapshot || null;
    const output = symbolState?.llm_output || null;
    renderMarketState(snapshot);
    renderMetrics(snapshot);
    renderLevels(snapshot);
    renderPatterns(symbolState);
    byId("llm-summary").textContent = output?.error
      ? output.error
      : output?.summary || "Not run.";
    renderSetups(output);
    byId("analysis-raw").textContent = snapshot
      ? JSON.stringify(snapshot, null, 2)
      : "No analysis snapshot yet.";
    byId("llm-raw").textContent = output
      ? JSON.stringify(output, null, 2)
      : "Not run.";
  }

  function renderActive({ chartChanged = false } = {}) {
    const symbol = state.activeSymbol;
    const symbolState = symbol ? state.symbols[symbol] : null;
    const quote = symbolState?.quote || {};

    byId("symbol").textContent = symbol || "--";
    byId("bid").textContent = fmtPrice(quote.bid);
    byId("ask").textContent = fmtPrice(quote.ask);
    byId("last").textContent = fmtPrice(quote.last);
    byId("volume").textContent = fmtVolume(quote.volume);
    const context = symbolState?.market_context || {};
    byId("security-status").textContent = context.halted ? "HALTED" : (context.security_status || "--");
    const htbRate = Number(context.hard_to_borrow_rate);
    byId("htb-status").textContent = context.hard_to_borrow === true
      ? "YES" + (Number.isFinite(htbRate) ? " " + htbRate.toFixed(1) + "%" : "")
      : context.hard_to_borrow === false ? "NO" : "--";
    const rsRank = Number(context.relative_strength_rank);
    const rsSize = Number(context.relative_strength_universe_size);
    byId("relative-strength").textContent = Number.isFinite(rsRank)
      ? "#" + rsRank + "/" + rsSize
      : "--";
    renderFreshness(symbolState);
    renderAnalysisView(symbolState);
    if (!symbolState) {
      candleSeries.setData([]);
      setPatternOverlays([], "LIVE:NONE");
      state.chartSymbol = null;
      state.chartRevision = null;
      state.chartFitSymbol = null;
      return;
    }

    const revision = `${symbolState.history_bars?.length || 0}:${symbolState.bars_10s?.length || 0}`;
    const symbolChanged = state.chartSymbol !== symbol;
    if (chartChanged || symbolChanged || state.chartRevision !== revision) {
      const bars = mergedBars(symbolState);
      candleSeries.setData(bars);
      volumeSeries.setData(
        bars.map((bar) => ({
          time: bar.time,
          value: Number.isFinite(bar.volume) ? Math.max(0, bar.volume) : 0,
        }))
      );
      vwapSeries.setData(vwapPoints(symbolState));
      ema9Series.setData(emaPoints(bars, 9));
      ema20Series.setData(emaPoints(bars, 20));
      setStructuralLines(symbolState.ae_snapshot);
      state.chartSymbol = symbol;
      state.chartRevision = revision;

      // Auto-fit only once when a symbol first has usable chart data.
      // Subsequent history/live bar updates must preserve the user's
      // manual zoom and pan range.
      if (bars.length > 0 && state.chartFitSymbol !== symbol) {
        chart.timeScale().fitContent();
        state.chartFitSymbol = symbol;
      }
    }
    setPatternOverlays(symbolState.pattern_observations || [], `LIVE:${symbol}`);
  }

  function applySnapshot(snapshot) {
    state.activeSymbol = snapshot.active_symbol;
    state.symbols = snapshot.symbols || {};
    const clientNow = Date.now();
    Object.values(state.symbols).forEach((symbolState) => {
      if (symbolState?.quote && symbolState.quote.received_at_ms != null) {
        symbolState.quote._client_received_at_ms = clientNow;
      }
    });
    byId("connection-state").textContent = snapshot.connection_state || "UNKNOWN";
    renderRecorderState(snapshot.recorder_state || {});
    if (!state.replayView) renderActive({ chartChanged: true });
  }

  function applyEvent(event) {
    if (event.type === "snapshot") {
      applySnapshot(event.payload);
      return;
    }

    if (event.type === "connection_state") {
      byId("connection-state").textContent = event.payload?.state || "UNKNOWN";
      return;
    }

    if (event.type === "active_symbol") {
      const nextSymbol = event.payload?.symbol || null;
      if (nextSymbol !== state.activeSymbol) {
        state.chartFitSymbol = null;
      }
      state.activeSymbol = nextSymbol;
      if (!state.replayView) renderActive();
      return;
    }

    const symbol = event.symbol;
    if (symbol && !state.symbols[symbol]) {
      state.symbols[symbol] = {
        quote: {},
        history_bars: [],
        vwap_points: [],
        bars_10s: [],
        ae_snapshot: null,
        pattern_observations: [],
      };
    }

    let chartChanged = false;
    if (event.type === "quote" && symbol) {
      state.symbols[symbol].quote = {
        ...(event.payload || {}),
        _client_received_at_ms: Date.now(),
      };
    } else if (event.type === "history" && symbol) {
      state.symbols[symbol].history_bars = event.payload?.bars || [];
      chartChanged = true;
    } else if (event.type === "completed_bar" && symbol) {
      state.symbols[symbol].bars_10s.push(event.payload);
      if (state.symbols[symbol].bars_10s.length > 600) {
        state.symbols[symbol].bars_10s.shift();
      }
      chartChanged = true;
    } else if (event.type === "vwap_points" && symbol) {
      if (event.payload?.point) {
        const points = state.symbols[symbol].vwap_points || [];
        const point = event.payload.point;
        if (points.length && points[points.length - 1].time === point.time) {
          points[points.length - 1] = point;
        } else {
          points.push(point);
        }
        state.symbols[symbol].vwap_points = points;
      } else {
        state.symbols[symbol].vwap_points = event.payload?.points || [];
      }
      chartChanged = true;
    } else if (event.type === "analysis_snapshot" && symbol) {
      state.symbols[symbol].ae_snapshot = event.payload?.snapshot || null;
      if (symbol === state.activeSymbol) {
        setStructuralLines(state.symbols[symbol].ae_snapshot);
      }
    } else if (event.type === "pattern_update" && symbol) {
      state.symbols[symbol].pattern_observations = event.payload?.patterns || [];
    } else if (event.type === "llm_update" && symbol) {
      state.symbols[symbol].llm_output = event.payload?.output || null;
      if (symbol === state.activeSymbol) {
        const output = state.symbols[symbol].llm_output;
        byId("llm-run").disabled = false;
        if (output?.error) {
          byId("server-message").textContent = output.error;
          byId("server-message").classList.add("error");
        } else {
          byId("server-message").textContent = `LLM analysis complete for ${symbol}.`;
          byId("server-message").classList.remove("error");
        }
      }
    } else if (event.type === "recorder_state") {
      renderRecorderState(event.payload || {});
    }

    if (!state.replayView && (!symbol || symbol === state.activeSymbol)) {
      renderActive({ chartChanged });
    }
  }

  function renderReplayView() {
    const payload = state.replaySnapshot;
    const replay = payload?.replay || {};
    const replaySession = payload?.session || {};
    const symbol = replay.symbol || null;
    const symbolState = symbol ? replaySession.symbols?.[symbol] : null;
    const quote = symbolState?.quote || {};

    byId("symbol").textContent = symbol || "--";
    byId("bid").textContent = fmtPrice(quote.bid);
    byId("ask").textContent = fmtPrice(quote.ask);
    byId("last").textContent = fmtPrice(quote.last);
    byId("volume").textContent = fmtVolume(quote.volume);

    const freshness = byId("quote-freshness");
    freshness.classList.remove("live", "delayed", "stale", "no-data");
    freshness.classList.add("replay");
    freshness.textContent = "REPLAY";

    renderAnalysisView(symbolState);
    if (!symbolState) {
      candleSeries.setData([]);
      volumeSeries.setData([]);
      vwapSeries.setData([]);
      ema9Series.setData([]);
      ema20Series.setData([]);
      setStructuralLines(null);
      setPatternOverlays([], "REPLAY:NONE");
      state.chartSymbol = null;
      state.chartRevision = null;
      return;
    }

    const bars = mergedBars(symbolState);
    const chartKey = `REPLAY:${replay.session_id || ""}:${symbol}`;
    const revision = `${chartKey}:${replay.cursor || 0}`;
    if (state.chartSymbol !== chartKey || state.chartRevision !== revision) {
      candleSeries.setData(bars);
      volumeSeries.setData(
        bars.map((bar) => ({
          time: bar.time,
          value: Number.isFinite(bar.volume) ? Math.max(0, bar.volume) : 0,
        }))
      );
      vwapSeries.setData(vwapPoints(symbolState));
      ema9Series.setData(emaPoints(bars, 9));
      ema20Series.setData(emaPoints(bars, 20));
      setStructuralLines(symbolState.ae_snapshot);
      state.chartSymbol = chartKey;
      state.chartRevision = revision;
      if (bars.length > 0 && state.chartFitSymbol !== chartKey) {
        chart.timeScale().fitContent();
        state.chartFitSymbol = chartKey;
      }
    }
    setPatternOverlays(symbolState.pattern_observations || [], chartKey);
  }

  function renderReplayState(payload) {
    const previousReplay = state.replaySnapshot?.replay || {};
    const nextReplay = payload?.replay || {};
    if (
      previousReplay.session_id === nextReplay.session_id
      && previousReplay.symbol === nextReplay.symbol
      && Number(nextReplay.cursor || 0) < Number(previousReplay.cursor || 0)
    ) {
      const rewindKey = `REPLAY:${nextReplay.session_id || ""}:${nextReplay.symbol || ""}`;
      delete state.patternTriggerHistory[rewindKey];
      state.patternOverlayRevision = null;
    }
    state.replaySnapshot = payload;
    const replay = payload?.replay || {};
    const status = String(replay.status || "EMPTY");
    const total = Number(replay.total_events || 0);
    const cursor = Number(replay.cursor || 0);
    const progress = Number(replay.progress || 0);

    byId("replay-status").textContent = status;
    byId("replay-status").classList.toggle("active", status === "PLAYING");
    byId("replay-status").classList.toggle("inactive", status !== "PLAYING");
    byId("replay-events").textContent = `${cursor.toLocaleString()} / ${total.toLocaleString()}`;
    byId("replay-percent").textContent = `${(progress * 100).toFixed(1)}%`;
    byId("replay-time").textContent = replay.current_ts_ms
      ? formatEasternTime(Number(replay.current_ts_ms) / 1000)
      : "--";

    const slider = byId("replay-progress");
    slider.max = String(total);
    slider.value = String(Math.min(cursor, total));
    slider.disabled = total === 0;

    byId("replay-play").disabled = total === 0 || status === "PLAYING" || status === "COMPLETE";
    byId("replay-pause").disabled = status !== "PLAYING";
    byId("replay-step").disabled = total === 0 || status === "PLAYING" || status === "COMPLETE";

    if (state.replayView) renderReplayView();
  }

  function populateReplaySymbols() {
    const sessionId = byId("replay-session").value;
    const selected = state.replaySessions.find((item) => item.session_id === sessionId);
    const select = byId("replay-symbol");
    select.replaceChildren();
    for (const symbol of selected?.symbols || []) {
      const option = document.createElement("option");
      option.value = symbol;
      option.textContent = symbol;
      select.appendChild(option);
    }
  }

  async function loadReplaySessions() {
    try {
      const response = await fetch("/api/replay/sessions", { cache: "no-store" });
      const sessions = await parseResponse(response);
      if (!response.ok) throw new Error("Unable to load replay sessions");
      state.replaySessions = Array.isArray(sessions) ? sessions : [];
      const select = byId("replay-session");
      select.replaceChildren();
      for (const session of state.replaySessions) {
        const option = document.createElement("option");
        option.value = session.session_id;
        const start = session.started_at_et ? new Date(session.started_at_et).toLocaleDateString() : session.session_id;
        option.textContent = `${start} · ${(session.symbols || []).length} tickers`;
        select.appendChild(option);
      }
      populateReplaySymbols();
      byId("replay-message").textContent = state.replaySessions.length
        ? "Choose a session and ticker, then Load."
        : "No recorded sessions found.";
    } catch (error) {
      byId("replay-message").textContent = error.message;
      byId("replay-message").classList.add("error");
    }
  }

  async function replayPost(path, body = null) {
    const options = { method: "POST" };
    if (body !== null) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
    const response = await fetch(path, options);
    const payload = await parseResponse(response);
    if (!response.ok) throw new Error(payload.detail || "Replay request failed");
    renderReplayState(payload);
    return payload;
  }

  async function refreshReplayState() {
    try {
      const response = await fetch("/api/replay/state", { cache: "no-store" });
      const payload = await parseResponse(response);
      if (response.ok) renderReplayState(payload);
    } catch (_error) {
      // Live operation remains independent if replay inspection fails.
    }
  }

  async function refreshAuthStatus() {
    try {
      const response = await fetch("/api/auth/status");
      const payload = await response.json();
      if (payload.authorized) {
        byId("auth-status").textContent = "Schwab auth: companion_auth authorized";
        byId("auth-status").classList.remove("error");
      } else {
        byId("auth-status").textContent =
          "Schwab auth: authorization required in companion_auth";
        byId("auth-status").classList.add("error");
      }
    } catch (_error) {
      byId("auth-status").textContent = "Schwab auth: status unavailable";
      byId("auth-status").classList.add("error");
    }
  }

  function connect() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${location.host}/ws`);
    state.socket = socket;

    socket.onopen = () => {
      byId("server-message").textContent = "Browser connected to joelab service.";
      byId("server-message").classList.remove("error");
    };

    socket.onmessage = (message) => {
      try {
        applyEvent(JSON.parse(message.data));
      } catch (error) {
        console.error("Bad websocket payload", error);
      }
    };

    socket.onclose = () => {
      byId("server-message").textContent = "Server connection lost; reconnecting...";
      byId("server-message").classList.add("error");
      clearTimeout(state.reconnectTimer);
      state.reconnectTimer = setTimeout(connect, 1500);
    };
  }

  async function parseResponse(response) {
    const text = await response.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch (_error) {
      const preview = text.replace(/\s+/g, " ").slice(0, 240);
      throw new Error(
        `Server returned non-JSON response (HTTP ${response.status}): ${preview}`
      );
    }
  }


  async function waitForLlmResult(symbol, timeoutMs = 125000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      try {
        const response = await fetch("/api/state", { cache: "no-store" });
        const snapshot = await parseResponse(response);
        if (!response.ok) continue;
        const symbolState = snapshot?.symbols?.[symbol];
        if (!symbolState?.llm_output) continue;

        state.activeSymbol = snapshot.active_symbol;
        state.symbols = snapshot.symbols || {};
        renderActive();
        byId("llm-run").disabled = false;

        const output = symbolState.llm_output;
        if (output?.error) {
          byId("server-message").textContent = output.error;
          byId("server-message").classList.add("error");
        } else {
          byId("server-message").textContent = `LLM analysis complete for ${symbol}.`;
          byId("server-message").classList.remove("error");
        }
        return;
      } catch (_error) {
        // WebSocket remains primary; polling is only a resilience fallback.
      }
    }

    byId("llm-run").disabled = false;
    byId("server-message").textContent =
      `LLM analysis did not return within ${Math.round(timeoutMs / 1000)}s.`;
    byId("server-message").classList.add("error");
  }

  byId("llm-run").addEventListener("click", async () => {
    const symbol = state.activeSymbol;
    if (!symbol) {
      byId("server-message").textContent = "Select a symbol before running LLM analysis.";
      byId("server-message").classList.add("error");
      return;
    }
    byId("llm-run").disabled = true;
    byId("server-message").textContent = `Starting LLM analysis for ${symbol}...`;
    byId("server-message").classList.remove("error");
    try {
      const response = await fetch(`/api/llm/run/${encodeURIComponent(symbol)}`, {
        method: "POST",
      });
      const payload = await parseResponse(response);
      if (!response.ok) throw new Error(payload.detail || "LLM analysis failed");
      byId("server-message").textContent = payload.already_running
        ? `LLM analysis already running for ${symbol}...`
        : `LLM analysis running for ${symbol}; waiting for server result...`;
      void waitForLlmResult(symbol);
    } catch (error) {
      byId("llm-run").disabled = false;
      byId("server-message").textContent = error.message;
      byId("server-message").classList.add("error");
    }
  });

  async function addRecordingSymbol(symbol) {
    const normalized = String(symbol || "").trim().toUpperCase();
    if (!normalized) {
      setRecordingMessage("Enter a ticker to add.", true);
      return;
    }

    const rawVwap = String(byId("recorder-pre7-vwap")?.value || "").trim();
    const rawVolume = String(byId("recorder-pre7-volume")?.value || "").replaceAll(",", "").trim();
    const hasVwap = rawVwap !== "";
    const hasVolume = rawVolume !== "";

    if (hasVwap !== hasVolume) {
      setRecordingMessage("Enter both PRE7 VWAP and PRE7 VOL, or leave both blank.", true);
      return;
    }

    const request = { symbol: normalized };
    if (hasVwap && hasVolume) {
      const pre7Vwap = Number(rawVwap);
      const pre7Volume = Number(rawVolume);
      if (!Number.isFinite(pre7Vwap) || pre7Vwap <= 0 || !Number.isFinite(pre7Volume) || pre7Volume < 0) {
        setRecordingMessage("PRE7 VWAP must be > 0 and PRE7 VOL must be 0 or greater.", true);
        return;
      }
      request.pre7_vwap = pre7Vwap;
      request.pre7_volume = pre7Volume;
    }

    try {
      const response = await fetch("/api/recording/symbol", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      const payload = await parseResponse(response);
      if (!response.ok) throw new Error(payload.detail || "Unable to add ticker");
      renderRecorderState(payload);
      byId("recorder-symbol").value = "";
      byId("recorder-pre7-vwap").value = "";
      byId("recorder-pre7-volume").value = "";
      setRecordingMessage(
        request.pre7_vwap !== undefined
          ? `${normalized} is recording with PRE7 VWAP seed applied.`
          : `${normalized} is now recording. PRE7 seed can be added by entering the ticker again with both values.`
      );
    } catch (error) {
      setRecordingMessage(error.message, true);
    }
  }

  async function removeRecordingSymbol(symbol) {
    const normalized = String(symbol || "").trim().toUpperCase();
    try {
      const response = await fetch(`/api/recording/symbol/${encodeURIComponent(normalized)}`, {
        method: "DELETE",
      });
      const payload = await parseResponse(response);
      if (!response.ok) throw new Error(payload.detail || "Unable to remove ticker");
      renderRecorderState(payload);
      setRecordingMessage(`${normalized} stopped recording. Existing data was preserved.`);
    } catch (error) {
      setRecordingMessage(error.message, true);
    }
  }

  byId("record-start").addEventListener("click", async () => {
    try {
      const response = await fetch("/api/recording/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols: [] }),
      });
      const payload = await parseResponse(response);
      if (!response.ok) throw new Error(payload.detail || "Recorder start failed");
      renderRecorderState(payload);
      setRecordingMessage("Recording session started. Add tickers as they appear.");
    } catch (error) {
      setRecordingMessage(error.message, true);
    }
  });

  byId("record-stop").addEventListener("click", async () => {
    try {
      const response = await fetch("/api/recording/stop", { method: "POST" });
      const payload = await parseResponse(response);
      if (!response.ok) throw new Error(payload.detail || "Recorder stop failed");
      renderRecorderState(payload);
      setRecordingMessage("Recording session stopped. All captured files were preserved.");
    } catch (error) {
      setRecordingMessage(error.message, true);
    }
  });

  byId("record-add-symbol").addEventListener("click", () => {
    void addRecordingSymbol(byId("recorder-symbol").value);
  });

  byId("recorder-symbol").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void addRecordingSymbol(byId("recorder-symbol").value);
    }
  });

  byId("record-add-active").addEventListener("click", () => {
    void addRecordingSymbol(state.activeSymbol);
  });

  byId("replay-session").addEventListener("change", populateReplaySymbols);

  byId("replay-load").addEventListener("click", async () => {
    const sessionId = byId("replay-session").value;
    const symbol = byId("replay-symbol").value;
    if (!sessionId || !symbol) {
      byId("replay-message").textContent = "Choose a recorded session and ticker first.";
      return;
    }
    try {
      const payload = await replayPost("/api/replay/load", {
        session_id: sessionId,
        symbol,
      });
      byId("replay-message").textContent =
        `Loaded ${symbol}: ${Number(payload?.replay?.total_events || 0).toLocaleString()} recorded events.`;
      byId("replay-message").classList.remove("error");
    } catch (error) {
      byId("replay-message").textContent = error.message;
      byId("replay-message").classList.add("error");
    }
  });

  byId("replay-play").addEventListener("click", async () => {
    try {
      await replayPost("/api/replay/play", { speed: byId("replay-speed").value });
      byId("replay-message").textContent = "Replay running.";
      byId("replay-message").classList.remove("error");
    } catch (error) {
      byId("replay-message").textContent = error.message;
      byId("replay-message").classList.add("error");
    }
  });

  byId("replay-pause").addEventListener("click", async () => {
    try {
      await replayPost("/api/replay/pause");
      byId("replay-message").textContent = "Replay paused.";
    } catch (error) {
      byId("replay-message").textContent = error.message;
      byId("replay-message").classList.add("error");
    }
  });

  byId("replay-step").addEventListener("click", async () => {
    try {
      await replayPost("/api/replay/step", { count: 1 });
      byId("replay-message").textContent = "Advanced one recorded event.";
    } catch (error) {
      byId("replay-message").textContent = error.message;
      byId("replay-message").classList.add("error");
    }
  });

  byId("replay-progress").addEventListener("change", async (event) => {
    try {
      const cursor = Number(event.target.value || 0);
      byId("replay-message").textContent = "Rebuilding replay state to selected point...";
      await replayPost("/api/replay/seek", { cursor });
      byId("replay-message").textContent = "Replay position rebuilt deterministically.";
      byId("replay-message").classList.remove("error");
    } catch (error) {
      byId("replay-message").textContent = error.message;
      byId("replay-message").classList.add("error");
    }
  });

  byId("symbol-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = byId("symbol-input");
    const symbol = input.value.trim().toUpperCase();
    if (!symbol) return;
    input.value = symbol;
    byId("server-message").textContent = `Loading ${symbol}...`;
    byId("server-message").classList.remove("error");

    try {
      const response = await fetch(`/api/symbol/${encodeURIComponent(symbol)}`, {
        method: "POST",
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Symbol load failed");
      }
      applySnapshot(payload);
      byId("server-message").textContent = `${symbol} loaded.`;
    } catch (error) {
      byId("server-message").textContent = error.message;
      byId("server-message").classList.add("error");
    }
  });

  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => setTab(button.dataset.tab));
  });

  byId("view-all-setups").addEventListener("click", () => setTab("setups"));

  byId("pattern-overlay-filters").addEventListener("click", (event) => {
    const button = event.target.closest("[data-pattern-type]");
    if (!button) return;
    const patternType = String(button.dataset.patternType || "").toUpperCase();
    if (!patternType) return;
    state.patternVisibility[patternType] = state.patternVisibility[patternType] === false;
    state.patternOverlayRevision = null;
    if (state.replayView) {
      renderReplayView();
    } else {
      renderActive();
    }
  });

  setInterval(() => {
    if (!state.replayView) {
      const symbolState = state.activeSymbol ? state.symbols[state.activeSymbol] : null;
      renderFreshness(symbolState);
    }
  }, 500);

  setInterval(() => {
    if (state.replayView) void refreshReplayState();
  }, 250);

  loadReplaySessions();
  refreshAuthStatus();
  connect();
})();
