(function () {
  const root = document.getElementById("dashboard-root");
  const refreshLabel = document.getElementById("last-refresh");
  const btnRefresh = document.getElementById("btn-refresh-monitor");
  const runStatus = document.getElementById("monitor-run-status");
  if (!root) return;

  let expandedTicker = null;

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function authHeaders() {
    return window.piaAuthHeaders?.() || {};
  }

  function tokenQuery() {
    return window.piaTokenQuery?.() || "";
  }

  function formatNumber(value, digits) {
    if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
    return Number(value).toFixed(digits);
  }

  function formatPct(value) {
    if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
    const n = Number(value);
    const sign = n > 0 ? "+" : "";
    return `${sign}${n.toFixed(1)}%`;
  }

  function formatAsOf(value) {
    if (!value) return "—";
    try {
      const d = new Date(value);
      if (Number.isNaN(d.getTime())) return escapeHtml(String(value));
      return escapeHtml(d.toLocaleString());
    } catch (_) {
      return escapeHtml(String(value));
    }
  }

  function renderDetail(signal) {
    const d = signal.detail || {};
    const indicators = d.indicators || {};
    const bullish = d.bullish || [];
    const bearish = d.bearish || [];
    const headlines = d.headlines || [];
    const assetClass = String(signal.asset_class || d.asset_class || "").toLowerCase();

    let flags = "";
    for (const item of bullish) {
      flags += `<span class="flag bullish">${escapeHtml(item)}</span>`;
    }
    for (const item of bearish) {
      flags += `<span class="flag bearish">${escapeHtml(item)}</span>`;
    }
    if (!flags) flags = `<span class="muted">No technical flags</span>`;

    let headlinesHtml = "";
    if (!headlines.length) {
      headlinesHtml = `<p class="muted">No headlines in the last Monitor run.</p>`;
    } else {
      headlinesHtml = `<ul class="headlines">`;
      for (const h of headlines) {
        const title = escapeHtml(h.headline || "");
        const source = escapeHtml(h.source || "");
        const sent =
          h.sentiment == null || Number.isNaN(Number(h.sentiment))
            ? "—"
            : Number(h.sentiment).toFixed(1);
        const body = h.link
          ? `<a href="${escapeHtml(h.link)}" target="_blank" rel="noopener noreferrer">${title}</a>`
          : title;
        headlinesHtml += `<li>${body}<div class="muted">${source} · sentiment ${sent}</div></li>`;
      }
      headlinesHtml += `</ul>`;
    }

    return `<div class="signal-detail">
      <div class="detail-grid">
        <div class="detail-item"><span class="label">Name</span>${escapeHtml(signal.name || signal.ticker)}</div>
        <div class="detail-item"><span class="label">Class</span>${escapeHtml(signal.asset_class || "—")}</div>
        <div class="detail-item"><span class="label">Close</span>${formatNumber(d.close, 2)}</div>
        <div class="detail-item"><span class="label">As of</span>${formatAsOf(d.as_of)}</div>
        <div class="detail-item"><span class="label">YTD</span>${formatPct(d.ytd_return_pct)}</div>
        ${
          assetClass === "etf" || assetClass === "etc"
            ? `<div class="detail-item"><span class="label">Vol (6mo)</span>${formatPct(d.std_dev_ann_pct)}</div>
        <div class="detail-item"><span class="label">Max DD (6mo)</span>${formatPct(d.max_drawdown_pct)}</div>`
            : ""
        }
        <div class="detail-item"><span class="label">Confidence</span>${escapeHtml(signal.confidence)}</div>
        <div class="detail-item"><span class="label">RSI 14</span>${formatNumber(indicators.rsi_14, 1)}</div>
        <div class="detail-item"><span class="label">MACD</span>${formatNumber(indicators.macd, 3)}</div>
      </div>
      <div>
        <div class="label muted" style="margin-bottom:0.35rem;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.04em;">Rationale</div>
        <p style="margin:0">${escapeHtml(signal.rationale || "—")}</p>
      </div>
      <div>
        <div class="label muted" style="margin-bottom:0.35rem;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.04em;">Technicals</div>
        <div class="flags">${flags}</div>
      </div>
      <div>
        <div class="label muted" style="margin-bottom:0.35rem;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.04em;">Headlines</div>
        ${headlinesHtml}
      </div>
      <p class="muted" style="margin:0;font-size:0.85rem">Click the row again to collapse.</p>
    </div>`;
  }

  function renderSignalsTable(signals) {
    let html = `<table class="signals-table"><thead>
      <tr><th></th><th>Instrument</th><th>Signal</th><th>Conf.</th><th>Summary</th></tr></thead><tbody>`;
    if (!signals || signals.length === 0) {
      html += `<tr><td colspan="5" class="muted">No signals for this class in the last run.</td></tr>`;
    } else {
      for (const s of signals) {
        const ticker = String(s.ticker || "").toUpperCase();
        const expanded = expandedTicker === ticker;
        html += `<tr class="signal-row" data-ticker="${escapeHtml(ticker)}" aria-expanded="${expanded ? "true" : "false"}" tabindex="0" role="button">
          <td>${s.emoji || ""}</td>
          <td>
            <div class="ticker-cell">
              <span class="ticker-symbol">${escapeHtml(ticker)}</span>
              <span class="ticker-name">${escapeHtml(s.name || ticker)}</span>
            </div>
          </td>
          <td class="signal-${String(s.signal).toLowerCase()}">${escapeHtml(s.signal)}</td>
          <td>${escapeHtml(s.confidence)}</td>
          <td class="rationale-preview">${escapeHtml(s.rationale_preview || s.rationale || "")}</td>
        </tr>`;
        if (expanded) {
          html += `<tr class="signal-detail-row"><td colspan="5">${renderDetail(s)}</td></tr>`;
        }
      }
    }
    return html + `</tbody></table>`;
  }

  function render(data) {
    if (!data.available) {
      root.innerHTML = `<p class="warn">${escapeHtml(data.message)}</p>`;
      return;
    }

    const counts = data.watchlist_counts || {};
    let html = "";
    if (data.stale_warning) {
      html += `<p class="warn">${escapeHtml(data.stale_warning)}</p>`;
    }
    html += `<dl class="meta-grid">
      <dt>Model</dt><dd>${escapeHtml(data.model)}</dd>
      <dt>Watchlist</dt><dd>${data.watchlist_count} total
        (stocks ${counts.stock || 0}, ETFs ${counts.etf || 0}, ETCs ${counts.etc || 0})</dd>
      <dt>Last run</dt><dd>${escapeHtml(data.last_run)}</dd>`;
    if (data.state_age_hours != null) {
      html += `<dt>Age</dt><dd>${data.state_age_hours}h</dd>`;
    }
    html += `</dl>`;

    const sections = data.sections || [];
    for (const section of sections) {
      html += `<h2>${escapeHtml(section.label)} <span class="muted">(${section.watchlist_count} on watchlist)</span></h2>`;
      html += renderSignalsTable(section.signals);
    }

    html += `<h2>Suggested</h2><ul class="suggestions">`;
    if (!data.suggestions || data.suggestions.length === 0) {
      html += `<li class="muted">None</li>`;
    } else {
      for (const line of data.suggestions) {
        html += `<li>${escapeHtml(line)}</li>`;
      }
    }
    html += `</ul><h2>Watchlist note</h2><p>${escapeHtml(data.watchlist_note || "None")}</p>`;
    if (data.errors && data.errors.length) {
      html += `<h2>Errors</h2><ul class="errors">`;
      for (const e of data.errors) {
        html += `<li>${escapeHtml(e)}</li>`;
      }
      html += `</ul>`;
    }
    root.innerHTML = html;
  }

  root.addEventListener("click", function (event) {
    const row = event.target.closest("tr.signal-row");
    if (!row || !root.contains(row)) return;
    const ticker = row.getAttribute("data-ticker");
    if (!ticker) return;
    expandedTicker = expandedTicker === ticker ? null : ticker;
    // Re-render from last payload if present
    if (root._lastData) render(root._lastData);
  });

  root.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest("tr.signal-row");
    if (!row || !root.contains(row)) return;
    event.preventDefault();
    row.click();
  });

  async function refresh() {
    try {
      const res = await fetch("/api/state" + tokenQuery(), {
        headers: authHeaders(),
      });
      if (!res.ok) return;
      const data = await res.json();
      root._lastData = data;
      render(data);
      if (refreshLabel) {
        refreshLabel.textContent = new Date().toLocaleTimeString();
      }
    } catch (_) {
      /* ignore polling errors */
    }
  }

  async function runMonitor() {
    if (!btnRefresh) return;
    btnRefresh.disabled = true;
    if (runStatus) runStatus.textContent = "Running Monitor… (may take a minute)";
    try {
      const res = await fetch("/api/monitor/run" + tokenQuery(), {
        method: "POST",
        headers: {
          ...authHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ run_type: "manual" }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 409) {
        if (runStatus) runStatus.textContent = "Already running — try again shortly.";
      } else if (!res.ok || data.status === "error") {
        if (runStatus) {
          runStatus.textContent =
            data.message || data.last_error || `Monitor failed (HTTP ${res.status})`;
        }
      } else {
        if (runStatus) runStatus.textContent = "Monitor finished.";
        await refresh();
      }
    } catch (err) {
      if (runStatus) runStatus.textContent = "Monitor request failed.";
    } finally {
      btnRefresh.disabled = false;
    }
  }

  if (btnRefresh) {
    btnRefresh.addEventListener("click", runMonitor);
  }

  // Prefer API payload; keep SSR until first fetch fills
  try {
    const initial = root.getAttribute("data-initial");
    if (initial) {
      root._lastData = JSON.parse(initial);
      render(root._lastData);
    }
  } catch (_) {
    /* ignore */
  }

  refresh();
  setInterval(refresh, 10000);
})();
