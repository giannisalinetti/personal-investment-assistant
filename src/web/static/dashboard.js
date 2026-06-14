(function () {
  const root = document.getElementById("dashboard-root");
  const refreshLabel = document.getElementById("last-refresh");
  if (!root) return;

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function render(data) {
    if (!data.available) {
      root.innerHTML = `<p class="warn">${escapeHtml(data.message)}</p>`;
      return;
    }

    let html = "";
    if (data.stale_warning) {
      html += `<p class="warn">${escapeHtml(data.stale_warning)}</p>`;
    }
    html += `<dl class="meta-grid">
      <dt>Model</dt><dd>${escapeHtml(data.model)}</dd>
      <dt>Watchlist</dt><dd>${data.watchlist_count} tickers</dd>
      <dt>Last run</dt><dd>${escapeHtml(data.last_run)}</dd>`;
    if (data.state_age_hours != null) {
      html += `<dt>Age</dt><dd>${data.state_age_hours}h</dd>`;
    }
    html += `</dl><h2>Signals</h2><table class="signals-table"><thead>
      <tr><th></th><th>Ticker</th><th>Signal</th><th>Conf.</th><th>Rationale</th></tr></thead><tbody>`;

    if (data.signals.length === 0) {
      html += `<tr><td colspan="5" class="muted">No signals in last run.</td></tr>`;
    } else {
      for (const s of data.signals) {
        html += `<tr>
          <td>${s.emoji}</td>
          <td><strong>${escapeHtml(s.ticker)}</strong></td>
          <td class="signal-${s.signal.toLowerCase()}">${escapeHtml(s.signal)}</td>
          <td>${escapeHtml(s.confidence)}</td>
          <td>${escapeHtml(s.rationale)}</td>
        </tr>`;
      }
    }
    html += `</tbody></table><h2>Suggested</h2><ul class="suggestions">`;
    if (data.suggestions.length === 0) {
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

  async function refresh() {
    try {
      const res = await fetch("/api/state" + (window.piaTokenQuery?.() || ""), {
        headers: window.piaAuthHeaders?.() || {},
      });
      if (!res.ok) return;
      const data = await res.json();
      render(data);
      if (refreshLabel) {
        refreshLabel.textContent = new Date().toLocaleTimeString();
      }
    } catch (_) {
      /* ignore polling errors */
    }
  }

  refresh();
  setInterval(refresh, 10000);
})();
