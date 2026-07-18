(function () {
  const editors = document.getElementById("watchlist-editors");
  const statusEl = document.getElementById("settings-status");
  const btnResetAll = document.getElementById("btn-reset-all");
  const CLASSES = ["stock", "etf", "etc"];

  function apiUrl(path) {
    return path + (window.piaTokenQuery?.() || "");
  }

  function apiFetch(path, options) {
    return fetch(apiUrl(path), {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options?.headers || {}),
        ...(window.piaAuthHeaders?.() || {}),
      },
    });
  }

  function showStatus(message, isError) {
    if (!statusEl) return;
    statusEl.hidden = false;
    statusEl.textContent = message;
    statusEl.classList.toggle("error", !!isError);
  }

  function rowsFromEntries(entries) {
    return (entries || []).map((e) => ({
      ticker: e.ticker || "",
      name: e.name || "",
    }));
  }

  function collectEntries(section) {
    const rows = section.querySelectorAll(".wl-row");
    const out = [];
    rows.forEach((row) => {
      const ticker = row.querySelector(".wl-ticker")?.value.trim().toUpperCase();
      const name = row.querySelector(".wl-name")?.value.trim();
      if (!ticker) return;
      out.push({ ticker, name: name || ticker });
    });
    return out;
  }

  function escapeAttr(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  }

  function renderRow(entry) {
    const div = document.createElement("div");
    div.className = "wl-row";
    div.innerHTML = `
      <input class="wl-ticker" type="text" maxlength="32" placeholder="Ticker" value="${escapeAttr(entry.ticker)}" autocomplete="off" spellcheck="false">
      <input class="wl-name" type="text" maxlength="120" placeholder="Name" value="${escapeAttr(entry.name)}" autocomplete="off">
      <button type="button" class="btn wl-remove" aria-label="Remove">Remove</button>
    `;
    div.querySelector(".wl-remove")?.addEventListener("click", () => div.remove());
    return div;
  }

  function setBadge(section, overridden) {
    const badge = section.querySelector(".wl-badge");
    if (!badge) return;
    badge.textContent = overridden ? "custom" : "YAML default";
    badge.classList.toggle("muted", !overridden);
  }

  function fillRows(section, entries) {
    const rowsEl = section.querySelector(".wl-rows");
    if (!rowsEl) return;
    rowsEl.innerHTML = "";
    rowsFromEntries(entries).forEach((entry) => rowsEl.appendChild(renderRow(entry)));
  }

  /** Refresh one class from a settings snapshot; leave other editors untouched. */
  function applyClassFromSnapshot(assetClass, data) {
    const section = editors.querySelector(`[data-asset-class="${assetClass}"]`);
    if (!section) return;
    const overridden = new Set(data.overridden_classes || []);
    fillRows(section, (data.effective || {})[assetClass] || []);
    setBadge(section, overridden.has(assetClass));
  }

  function renderEditor(assetClass, label, entries, overridden) {
    const section = document.createElement("section");
    section.className = "wl-class-editor";
    section.dataset.assetClass = assetClass;
    const badge = overridden
      ? '<span class="wl-badge">custom</span>'
      : '<span class="wl-badge muted">YAML default</span>';
    section.innerHTML = `
      <div class="wl-class-header">
        <h3>${label} ${badge}</h3>
        <div class="wl-class-actions">
          <button type="button" class="btn wl-add">Add</button>
          <button type="button" class="btn primary wl-save">Save</button>
          <button type="button" class="btn wl-reset">Reset class</button>
        </div>
      </div>
      <div class="wl-rows"></div>
    `;
    fillRows(section, entries);

    section.querySelector(".wl-add")?.addEventListener("click", () => {
      const rowsEl = section.querySelector(".wl-rows");
      rowsEl.appendChild(renderRow({ ticker: "", name: "" }));
      rowsEl.querySelector(".wl-row:last-child .wl-ticker")?.focus();
    });

    section.querySelector(".wl-save")?.addEventListener("click", async () => {
      const payload = {
        asset_class: assetClass,
        entries: collectEntries(section),
      };
      const res = await apiFetch("/api/settings/watchlists", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showStatus(data.detail || "Save failed", true);
        return;
      }
      // Only refresh this class — full reload would wipe unsaved edits in siblings.
      applyClassFromSnapshot(assetClass, data);
      showStatus(`Saved ${label} (${payload.entries.length} tickers).`);
    });

    section.querySelector(".wl-reset")?.addEventListener("click", async () => {
      if (!window.confirm(`Reset ${label} to YAML defaults?`)) return;
      const res = await apiFetch("/api/settings/watchlists/reset", {
        method: "POST",
        body: JSON.stringify({ asset_class: assetClass }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showStatus(data.detail || "Reset failed", true);
        return;
      }
      applyClassFromSnapshot(assetClass, data);
      showStatus(`Reset ${label} to YAML defaults.`);
    });

    return section;
  }

  async function load() {
    const res = await apiFetch("/api/settings/watchlists");
    if (!res.ok) {
      showStatus("Failed to load watchlists", true);
      return;
    }
    const data = await res.json();
    editors.innerHTML = "";
    const overridden = new Set(data.overridden_classes || []);
    const labels = data.labels || {};
    const effective = data.effective || {};
    CLASSES.forEach((assetClass) => {
      editors.appendChild(
        renderEditor(
          assetClass,
          labels[assetClass] || assetClass,
          effective[assetClass] || [],
          overridden.has(assetClass)
        )
      );
    });
  }

  btnResetAll?.addEventListener("click", async () => {
    if (!window.confirm("Reset all watchlists to YAML defaults? This removes your overlay.")) return;
    const res = await apiFetch("/api/settings/watchlists/reset", {
      method: "POST",
      body: JSON.stringify({}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showStatus(data.detail || "Reset failed", true);
      return;
    }
    showStatus("All classes reset to YAML defaults.");
    await load();
  });

  load().catch((err) => showStatus(String(err), true));
})();
