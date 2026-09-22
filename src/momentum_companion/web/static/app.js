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

  function vwapPoints(bars) {
    let cumulativePV = 0;
    let cumulativeVolume = 0;
    const points = [];
    for (const bar of bars) {
      const volume = Number.isFinite(bar.volume) ? Math.max(0, bar.volume) : 0;
      cumulativePV += bar.close * volume;
      cumulativeVolume += volume;
      if (cumulativeVolume > 0) {
        points.push({ time: bar.time, value: cumulativePV / cumulativeVolume });
      }
    }
    return points;
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

  function renderActive({ chartChanged = false } = {}) {
    const symbol = state.activeSymbol;
    const symbolState = symbol ? state.symbols[symbol] : null;
    const quote = symbolState?.quote || {};

    byId("symbol").textContent = symbol || "--";
    byId("bid").textContent = fmtPrice(quote.bid);
    byId("ask").textContent = fmtPrice(quote.ask);
    byId("last").textContent = fmtPrice(quote.last);
    byId("volume").textContent = fmtVolume(quote.volume);
    byId("analysis").textContent = symbolState?.ae_snapshot
      ? JSON.stringify(symbolState.ae_snapshot, null, 2)
      : "No analysis snapshot yet.";
    byId("llm-output").textContent = symbolState?.llm_output
      ? JSON.stringify(symbolState.llm_output, null, 2)
      : "Not run.";

    if (!symbolState) {
      candleSeries.setData([]);
      state.chartSymbol = null;
      state.chartRevision = null;
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
      vwapSeries.setData(vwapPoints(bars));
      ema9Series.setData(emaPoints(bars, 9));
      ema20Series.setData(emaPoints(bars, 20));
      setStructuralLines(symbolState.ae_snapshot);
      state.chartSymbol = symbol;
      state.chartRevision = revision;
      if (symbolChanged || chartChanged) {
        chart.timeScale().fitContent();
      }
    }
  }

  function applySnapshot(snapshot) {
    state.activeSymbol = snapshot.active_symbol;
    state.symbols = snapshot.symbols || {};
    byId("connection-state").textContent = snapshot.connection_state || "UNKNOWN";
    byId("recorder").textContent = JSON.stringify(snapshot.recorder_state || {}, null, 2);
    renderActive({ chartChanged: true });
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
      state.activeSymbol = event.payload?.symbol || null;
      renderActive();
      return;
    }

    const symbol = event.symbol;
    if (symbol && !state.symbols[symbol]) {
      state.symbols[symbol] = {
        quote: {},
        history_bars: [],
        bars_10s: [],
        ae_snapshot: null,
      };
    }

    let chartChanged = false;
    if (event.type === "quote" && symbol) {
      state.symbols[symbol].quote = event.payload || {};
    } else if (event.type === "history" && symbol) {
      state.symbols[symbol].history_bars = event.payload?.bars || [];
      chartChanged = true;
    } else if (event.type === "completed_bar" && symbol) {
      state.symbols[symbol].bars_10s.push(event.payload);
      if (state.symbols[symbol].bars_10s.length > 600) {
        state.symbols[symbol].bars_10s.shift();
      }
      chartChanged = true;
    } else if (event.type === "analysis_snapshot" && symbol) {
      state.symbols[symbol].ae_snapshot = event.payload?.snapshot || null;
      if (symbol === state.activeSymbol) {
        setStructuralLines(state.symbols[symbol].ae_snapshot);
      }
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
      byId("recorder").textContent = JSON.stringify(event.payload || {}, null, 2);
    }

    if (!symbol || symbol === state.activeSymbol) renderActive({ chartChanged });
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
    } catch (error) {
      byId("llm-run").disabled = false;
      byId("server-message").textContent = error.message;
      byId("server-message").classList.add("error");
    }
  });

  byId("record-start").addEventListener("click", async () => {
    const raw = byId("recorder-symbols").value.trim();
    const symbols = raw
      .split(",")
      .map((value) => value.trim().toUpperCase())
      .filter(Boolean);
    if (!symbols.length && state.activeSymbol) symbols.push(state.activeSymbol);
    if (!symbols.length) {
      byId("server-message").textContent = "Enter at least one recorder symbol.";
      byId("server-message").classList.add("error");
      return;
    }

    try {
      const response = await fetch("/api/recording/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Recorder start failed");
      byId("recorder").textContent = JSON.stringify(payload, null, 2);
      byId("server-message").textContent = `Recording ${symbols.join(", ")} until 3:00 PM ET.`;
      byId("server-message").classList.remove("error");
    } catch (error) {
      byId("server-message").textContent = error.message;
      byId("server-message").classList.add("error");
    }
  });

  byId("record-stop").addEventListener("click", async () => {
    try {
      const response = await fetch("/api/recording/stop", { method: "POST" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Recorder stop failed");
      byId("recorder").textContent = JSON.stringify(payload, null, 2);
      byId("server-message").textContent = "Recording stopped.";
      byId("server-message").classList.remove("error");
    } catch (error) {
      byId("server-message").textContent = error.message;
      byId("server-message").classList.add("error");
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

  refreshAuthStatus();
  connect();
})();
