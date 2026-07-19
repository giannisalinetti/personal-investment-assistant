(function () {
  const SESSION_KEY = "pia_advisor_session";
  const chat = document.getElementById("chat");
  const chatEmpty = document.getElementById("chat-empty");
  const status = document.getElementById("status");
  const form = document.getElementById("ask-form");
  const questionEl = document.getElementById("question");
  const btnNew = document.getElementById("btn-new");
  const btnBrief = document.getElementById("btn-brief");
  const btnClear = document.getElementById("btn-clear");
  const sidebarList = document.getElementById("sidebar-list");
  const sidebarEmpty = document.getElementById("sidebar-empty");

  let activeSource = null;
  let selectedExchangeId = null;
  let viewingHistory = false;
  let currentStream = null;

  function storage() {
    try {
      return window.localStorage;
    } catch (_) {
      return null;
    }
  }

  function apiUrl(path) {
    return path + (window.piaTokenQuery?.() || "");
  }

  function apiFetch(path, options) {
    return fetch(apiUrl(path), {
      ...options,
      headers: { ...(options?.headers || {}), ...(window.piaAuthHeaders?.() || {}) },
    });
  }

  function saveSession(state) {
    const store = storage();
    if (!store) return;
    try {
      store.setItem(SESSION_KEY, JSON.stringify(state));
    } catch (_) {
      /* quota or private mode */
    }
  }

  function readSession() {
    const store = storage();
    if (!store) return null;
    try {
      const raw = store.getItem(SESSION_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function clearSession() {
    storage()?.removeItem(SESSION_KEY);
  }

  function userHtmlForStream(mode, question) {
    if (mode === "brief") {
      return "<p><em>Daily brief</em></p>";
    }
    return `<p>${escapeHtml(question || "")}</p>`;
  }

  function persistActiveDraft(userHtml, assistantHtml, extra = {}) {
    const session = readSession() || {};
    saveSession({
      exchangeId: extra.exchangeId ?? session.exchangeId ?? selectedExchangeId ?? null,
      pending: extra.pending ?? null,
      mode: extra.mode ?? "active",
      draft: { userHtml, assistantHtml },
      stream: extra.stream ?? currentStream ?? session.stream ?? null,
    });
  }

  function snapshotBeforeLeave() {
    const users = chat.querySelectorAll(".chat-user .body");
    const assistants = chat.querySelectorAll(".chat-assistant .body");
    const userBody = users.length ? users[users.length - 1] : null;
    const assistantBody = assistants.length ? assistants[assistants.length - 1] : null;
    if (!userBody) return;

    const pending = readSession()?.pending ?? null;
    const streaming = Boolean(pending && !assistantBody);
    persistActiveDraft(
      userBody.innerHTML,
      assistantBody ? assistantBody.innerHTML : "",
      {
        pending: streaming ? pending : null,
        mode: streaming ? "streaming" : "active",
      }
    );
  }

  function setBusy(busy) {
    btnBrief.disabled = busy;
    btnNew.disabled = busy;
    if (questionEl) questionEl.disabled = busy;
    if (busy) form.classList.add("busy");
    else form.classList.remove("busy");
  }

  function showStatus(message) {
    status.hidden = false;
    status.textContent = message;
  }

  function hideStatus() {
    status.hidden = true;
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function clearMainChat() {
    chat.innerHTML = "";
    chat.appendChild(chatEmpty);
    chatEmpty.hidden = false;
    viewingHistory = false;
    selectedExchangeId = null;
    currentStream = null;
    document.querySelectorAll(".sidebar-item").forEach((el) => el.classList.remove("active"));
  }

  /** Leave a read-only history view so the next message starts a live accumulating thread. */
  function leaveHistoryViewIfNeeded() {
    if (!viewingHistory) {
      chat.querySelector(".history-note")?.remove();
      return;
    }
    clearMainChat();
  }

  function renderExchange(userHtml, assistantHtml, { readOnly = false } = {}) {
    chatEmpty.hidden = true;
    chat.innerHTML = "";

    const userDiv = document.createElement("div");
    userDiv.className = "chat-turn chat-user";
    userDiv.innerHTML = `<span class="role">You</span><div class="body prose">${userHtml}</div>`;

    chat.appendChild(userDiv);

    if (assistantHtml) {
      const assistantDiv = document.createElement("div");
      assistantDiv.className = "chat-turn chat-assistant";
      assistantDiv.innerHTML = `<span class="role">Advisor</span><div class="body prose">${assistantHtml}</div>`;
      chat.appendChild(assistantDiv);
    }

    if (readOnly) {
      const note = document.createElement("p");
      note.className = "history-note muted";
      note.textContent = "Viewing a previous chat — send a new message or click New chat.";
      chat.appendChild(note);
    }
    chat.scrollTop = 0;
  }

  function plainTurnToHtml(content) {
    const text = String(content || "");
    if (!text.trim()) return "<p></p>";
    return text
      .split(/\n\n+/)
      .map((para) => `<p>${escapeHtml(para).replace(/\n/g, "<br>")}</p>`)
      .join("");
  }

  function appendTurnHtml(role, bodyHtml) {
    chatEmpty.hidden = true;
    const div = document.createElement("div");
    div.className = `chat-turn chat-${role === "assistant" ? "assistant" : "user"}`;
    const label = role === "assistant" ? "Advisor" : "You";
    div.innerHTML = `<span class="role">${label}</span><div class="body prose">${bodyHtml}</div>`;
    chat.appendChild(div);
  }

  function appendUserTurn(text) {
    appendTurnHtml("user", `<p>${escapeHtml(text)}</p>`);
    chat.scrollTop = chat.scrollHeight;
  }

  function appendAssistantTurn(html) {
    appendTurnHtml("assistant", html);
    chat.scrollTop = chat.scrollHeight;
  }

  function renderThreadFromTurns(turns) {
    chat.innerHTML = "";
    chat.appendChild(chatEmpty);
    if (!turns.length) {
      chatEmpty.hidden = false;
      return;
    }
    chatEmpty.hidden = true;
    for (const turn of turns) {
      const role = turn.role === "assistant" ? "assistant" : "user";
      appendTurnHtml(role, plainTurnToHtml(turn.content));
    }
    viewingHistory = false;
    chat.scrollTop = chat.scrollHeight;
  }

  async function hydrateThreadFromHistory() {
    const res = await apiFetch("/api/advisor/history");
    if (!res.ok) return false;
    const data = await res.json();
    const turns = Array.isArray(data.turns) ? data.turns : [];
    if (!turns.length) return false;
    renderThreadFromTurns(turns);
    return true;
  }

  function matchesPending(preview, pending) {
    const p = (preview || "").toLowerCase();
    if (pending.mode === "brief") {
      return p === "/brief" || p.startsWith("daily brief");
    }
    const q = (pending.question || "").trim().toLowerCase();
    if (!q) return false;
    return p === q || q.startsWith(p.replace(/…$/, "")) || p.startsWith(q.slice(0, 40));
  }

  function highlightSidebar(id) {
    document.querySelectorAll(".sidebar-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.id === String(id));
    });
  }

  async function loadSidebar() {
    const res = await apiFetch("/api/advisor/exchanges");
    if (!res.ok) return [];
    const data = await res.json();
    const items = data.exchanges || [];
    sidebarList.innerHTML = "";
    sidebarEmpty.hidden = items.length > 0;

    for (const item of items) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sidebar-item";
      btn.dataset.id = String(item.id);
      btn.textContent = item.preview;
      if (selectedExchangeId === item.id) btn.classList.add("active");
      btn.addEventListener("click", () => selectExchange(item.id, { fromSidebar: true }));
      li.appendChild(btn);
      sidebarList.appendChild(li);
    }
    return items;
  }

  async function selectExchange(id, { fromSidebar = false, skipPersist = false } = {}) {
    selectedExchangeId = id;
    viewingHistory = fromSidebar;
    highlightSidebar(id);

    const res = await apiFetch(`/api/advisor/exchanges/${id}`);
    if (!res.ok) return;
    const exchange = await res.json();
    renderExchange(exchange.user_html, exchange.assistant_html, { readOnly: fromSidebar });
    hideStatus();

    if (!skipPersist) {
      saveSession({
        exchangeId: id,
        pending: null,
        mode: fromSidebar ? "view" : "active",
        draft: { userHtml: exchange.user_html, assistantHtml: exchange.assistant_html },
        stream: null,
      });
    }
  }

  function streamAdvisor(mode, question) {
    if (activeSource) {
      activeSource.close();
      activeSource = null;
    }

    viewingHistory = false;
    selectedExchangeId = null;
    currentStream = { mode, question };
    document.querySelectorAll(".sidebar-item").forEach((el) => el.classList.remove("active"));

    const userHtml = userHtmlForStream(mode, question);
    saveSession({
      exchangeId: null,
      pending: { mode, question, startedAt: Date.now() },
      mode: "streaming",
      draft: { userHtml, assistantHtml: "" },
      stream: currentStream,
    });

    const params = new URLSearchParams({ mode });
    if (question) params.set("question", question);
    const tokenQ = window.piaTokenQuery?.() || "";
    const url = `/api/advisor/stream${tokenQ ? `${tokenQ}&` : "?"}${params.toString()}`;

    setBusy(true);
    showStatus("Connecting…");

    const source = new EventSource(url);
    activeSource = source;

    source.addEventListener("status", (ev) => {
      try {
        const data = JSON.parse(ev.data);
        showStatus(data.message || "Working…");
      } catch (_) {
        showStatus("Working…");
      }
    });

    source.addEventListener("done", (ev) => {
      source.close();
      activeSource = null;
      setBusy(false);
      hideStatus();

      let assistantHtml = "<p><em>Empty response</em></p>";
      try {
        const data = JSON.parse(ev.data);
        assistantHtml = data.assistant_html || `<p>${escapeHtml(data.answer || "")}</p>`;
      } catch (_) {
        /* keep fallback */
      }

      appendAssistantTurn(assistantHtml);

      const userHtmlDone = userHtmlForStream(currentStream?.mode, currentStream?.question);
      persistActiveDraft(userHtmlDone, assistantHtml, { pending: null, mode: "active" });

      void (async () => {
        await loadSidebar();
        const listRes = await apiFetch("/api/advisor/exchanges");
        if (!listRes.ok) return;
        const newest = (await listRes.json()).exchanges?.[0];
        if (!newest) return;
        selectedExchangeId = newest.id;
        highlightSidebar(newest.id);
        saveSession({
          exchangeId: newest.id,
          pending: null,
          mode: "active",
          draft: { userHtml: userHtmlDone, assistantHtml },
          stream: null,
        });
      })();
    });

    source.addEventListener("error", (ev) => {
      let message = "Advisor request failed.";
      if (ev.data) {
        try {
          message = JSON.parse(ev.data).message || message;
        } catch (_) {
          /* default */
        }
      }
      source.close();
      activeSource = null;
      setBusy(false);
      showStatus(message);
      snapshotBeforeLeave();
    });

    source.onerror = () => {
      if (activeSource !== source) return;
      source.close();
      activeSource = null;
      setBusy(false);
      showStatus("Connection lost. Is pia-web still running?");
      snapshotBeforeLeave();
    };
  }

  async function restoreSession() {
    const session = readSession();
    const items = await loadSidebar();

    // Explicitly viewing a sidebar exchange — keep single-pair read-only view.
    if (session?.mode === "view" && session.exchangeId != null) {
      if (items.some((item) => item.id === session.exchangeId)) {
        await selectExchange(session.exchangeId, { fromSidebar: true, skipPersist: true });
        return;
      }
    }

    // Incomplete stream: show full thread + pending user draft if needed.
    if (session?.pending && !session.draft?.assistantHtml) {
      const hydrated = await hydrateThreadFromHistory();
      if (!hydrated && session.draft?.userHtml) {
        renderExchange(session.draft.userHtml, "", { readOnly: false });
      } else if (hydrated && session.draft?.userHtml) {
        // Pending ask may not be persisted yet — append the in-flight user turn.
        appendTurnHtml("user", session.draft.userHtml);
        chat.scrollTop = chat.scrollHeight;
      }
      selectedExchangeId = session.exchangeId ?? null;
      currentStream = session.stream ?? null;
      showStatus("Advisor may still be working on this — check back in a moment or pick History.");
      const match = items.find((item) => matchesPending(item.preview, session.pending));
      if (match) {
        selectedExchangeId = match.id;
        highlightSidebar(match.id);
      }
      return;
    }

    // Default: show the full persisted thread in the main pane.
    const hydrated = await hydrateThreadFromHistory();
    if (hydrated) {
      hideStatus();
      if (items.length) {
        selectedExchangeId = items[0].id;
        highlightSidebar(items[0].id);
      }
      return;
    }

    if (session?.draft?.userHtml) {
      renderExchange(
        session.draft.userHtml,
        session.draft.assistantHtml || "",
        { readOnly: false }
      );
      selectedExchangeId = session.exchangeId ?? null;
      currentStream = session.stream ?? null;
      hideStatus();
      if (selectedExchangeId != null) highlightSidebar(selectedExchangeId);
    }
  }

  form?.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = questionEl.value.trim();
    if (!q) return;
    leaveHistoryViewIfNeeded();
    chatEmpty.hidden = true;
    appendUserTurn(q);
    questionEl.value = "";
    streamAdvisor("ask", q);
  });

  questionEl?.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" || ev.shiftKey) return;
    if (ev.isComposing) return;
    ev.preventDefault();
    if (questionEl.disabled) return;
    form?.requestSubmit();
  });

  btnNew?.addEventListener("click", () => {
    clearMainChat();
    hideStatus();
    clearSession();
    questionEl.focus();
  });

  btnBrief?.addEventListener("click", () => {
    leaveHistoryViewIfNeeded();
    chatEmpty.hidden = true;
    appendTurnHtml("user", "<p><em>Daily brief</em></p>");
    chat.scrollTop = chat.scrollHeight;
    streamAdvisor("brief", "");
  });

  btnClear?.addEventListener("click", async () => {
    if (!window.confirm("Clear all Advisor history? This cannot be undone.")) return;
    const res = await apiFetch("/api/advisor/clear", { method: "POST" });
    if (res.ok) {
      clearMainChat();
      hideStatus();
      clearSession();
      await loadSidebar();
    }
  });

  window.addEventListener("pagehide", snapshotBeforeLeave);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") snapshotBeforeLeave();
  });

  restoreSession();
})();
