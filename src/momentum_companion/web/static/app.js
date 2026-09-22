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
    patternSeries: [],
    selectedPatternId: null,
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

  function addLineSeries(options = {}) {
    return typeof chart.addLineSeries === "function"
      ? chart.addLineSeries(options)
      : chart.addSeries(LightweightCharts.LineSeries, options);
  }

  function clearPatternOverlays() {
    for (const entry of state.patternSeries) {
      try {
        chart.removeSeries(entry.series);
      } catch (_error) {
        // A stale browser series must never break live chart updates.
      }
    }
    state.patternSeries = [];
  }

  function humanizePatternName(value) {
    return String(value || "PATTERN")
      .toLowerCase()
      .split("_")
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  }

  function formatEvidence(pattern) {
    const evidence = pattern?.evidence || {};
    if (pattern?.pattern_type === "ASCENDING_TRIANGLE") {
      const touches = evidence.resistance_touches;
      const lows = evidence.higher_lows;
      const compression = evidence.compression_pct;
      const resistance = evidence.resistance;
      const parts = [];
      if (Number.isFinite(Number(resistance))) parts.push(`R ${fmtPrice(resistance)}`);
      if (touches !== undefined) parts.push(`${touches} touches`);
      if (lows !== undefined) parts.push(`${lows} rising lows`);
      if (Number.isFinite(Number(compression))) parts.push(`${Number(compression).toFixed(0)}% compressed`);
      return parts.join(" · ");
    }
    if (pattern?.pattern_type === "MICRO_PULLBACK") {
      const parts = [];
      if (evidence.duration_sec !== undefined) parts.push(`${Number(evidence.duration_sec).toFixed(0)} sec`);
      if (Number.isFinite(Number(evidence.retracement_pct))) {
        parts.push(`${(Number(evidence.retracement_pct) * 100).toFixed(0)}% retrace`);
      }
      if (Number.isFinite(Number(evidence.continuation_level))) {
        parts.push(`trigger ${fmtPrice(evidence.continuation_level)}`);
      }
      return parts.join(" · ");
    }
    const entries = Object.entries(evidence)
      .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value))
      .slice(0, 3);
    return entries.map(([key, value]) => `${key}: ${value}`).join(" · ");
  }

  function renderPatternOverlays(patterns) {
    clearPatternOverlays();

    for (const pattern of patterns || []) {
      for (const line of pattern.lines || []) {
        const startTime = Number(line?.start?.time);
        const endTime = Number(line?.end?.time);
        const startPrice = Number(line?.start?.price);
        const endPrice = Number(line?.end?.price);
        if (![startTime, endTime, startPrice, endPrice].every(Number.isFinite)) continue;

        const selected = state.selectedPatternId === pattern.id;
        const series = addLineSeries({
          lineWidth: selected ? 3 : 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        series.setData([
          { time: startTime, value: startPrice },
          { time: endTime, value: endPrice },
        ]);
        state.patternSeries.push({
          series,
          patternId: pattern.id,
          role: line.role,
        });
      }
    }
  }

  function selectPattern(patternId) {
    state.selectedPatternId = state.selectedPatternId === patternId ? null : patternId;
    renderActive();
  }

  function renderPatternPanel(patterns) {
    const root = byId("patterns");
    const list = Array.isArray(patterns) ? patterns : [];
    byId("pattern-count").textContent = String(list.length);
    root.replaceChildren();

    if (!list.length) {
      const empty = document.createElement("div");
      empty.className = "pattern-empty";
      empty.textContent = "No active patterns.";
      root.appendChild(empty);
      return;
    }

    for (const pattern of list) {
      const item = document.createElement("div");
      item.className = "pattern-item";
      if (state.selectedPatternId === pattern.id) item.classList.add("active");
      item.dataset.patternId = pattern.id || "";
      item.dataset.state = pattern.state || "";
      item.tabIndex = 0;

      const row = document.createElement("div");
      row.className = "pattern-row";

      const name = document.createElement("div");
      name.className = "pattern-name";
      name.textContent = humanizePatternName(pattern.pattern_type);

      const status = document.createElement("div");
      status.className = "pattern-state";
      status.textContent = pattern.state || "UNKNOWN";

      row.append(name, status);
      item.appendChild(row);

      const evidenceText = formatEvidence(pattern);
      if (evidenceText) {
        const evidence = document.createElement("div");
        evidence.className = "pattern-evidence";
        evidence.textContent = evidenceText;
        item.appendChild(evidence);
      }

      const choose = () => selectPattern(pattern.id);
      item.addEventListener("click", choose);
      item.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          choose();
        }
      });
      root.appendChild(item);
    }
  }

  function normalizeBar(bar) {
    return {
      time: Number(bar.time ?? bar.ts),
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
    };
  }

  function renderActive() {
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

    const patterns = symbolState?.pattern_observations || [];
    if (
      state.selectedPatternId &&
      !patterns.some((pattern) => pattern.id === state.selectedPatternId)
    ) {
      state.selectedPatternId = null;
    }
    renderPatternPanel(patterns);

    const history = symbolState?.history_bars || [];
    const live = symbolState?.bars_10s || [];
    const all = [...history, ...live]
      .filter((bar) => bar && (bar.time !== undefined || bar.ts !== undefined))
      .map(normalizeBar)
      .filter((bar) => Number.isFinite(bar.time) && Number.isFinite(bar.close));

    candleSeries.setData(all);
    renderPatternOverlays(patterns);
  }

  function applySnapshot(snapshot) {
    state.activeSymbol = snapshot.active_symbol;
    state.symbols = snapshot.symbols || {};
    byId("connection-state").textContent = snapshot.connection_state || "UNKNOWN";
    byId("recorder").textContent = JSON.stringify(snapshot.recorder_state || {}, null, 2);
    renderActive();
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
        llm_output: null,
        pattern_observations: [],
      };
    }

    if (event.type === "quote" && symbol) {
      state.symbols[symbol].quote = event.payload || {};
    } else if (event.type === "history" && symbol) {
      state.symbols[symbol].history_bars = event.payload?.bars || [];
    } else if (event.type === "completed_bar" && symbol) {
      state.symbols[symbol].bars_10s.push(event.payload);
      if (state.symbols[symbol].bars_10s.length > 600) {
        state.symbols[symbol].bars_10s.shift();
      }
    } else if (event.type === "analysis_snapshot" && symbol) {
      state.symbols[symbol].ae_snapshot = event.payload?.snapshot || null;
    } else if (event.type === "llm_update" && symbol) {
      state.symbols[symbol].llm_output = event.payload?.output || null;
    } else if (event.type === "pattern_update" && symbol) {
      state.symbols[symbol].pattern_observations = event.payload?.patterns || [];
    } else if (event.type === "recorder_state") {
      byId("recorder").textContent = JSON.stringify(event.payload || {}, null, 2);
    }

    if (!symbol || symbol === state.activeSymbol) renderActive();
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

  byId("llm-run").addEventListener("click", async () => {
    const symbol = state.activeSymbol;
    if (!symbol) {
      byId("server-message").textContent = "Select a symbol before running LLM analysis.";
      byId("server-message").classList.add("error");
      return;
    }
    byId("server-message").textContent = `Running LLM analysis for ${symbol}...`;
    byId("server-message").classList.remove("error");
    try {
      const response = await fetch(`/api/llm/run/${encodeURIComponent(symbol)}`, {
        method: "POST",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "LLM analysis failed");
      state.symbols[symbol].llm_output = payload;
      renderActive();
      byId("server-message").textContent = `LLM analysis complete for ${symbol}.`;
    } catch (error) {
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
