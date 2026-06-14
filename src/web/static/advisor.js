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
  const btnAsk = document.getElementById("btn-ask");
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
    const userBody = chat.querySelector(".chat-user .body");
    const assistantBody = chat.querySelector(".chat-assistant .body");
    if (!userBody) return;

    persistActiveDraft(
      userBody.innerHTML,
      assistantBody ? assistantBody.innerHTML : "",
      {
        pending: assistantBody ? null : readSession()?.pending ?? null,
        mode: assistantBody ? "active" : "streaming",
      }
    );
  }

  function setBusy(busy) {
    btnBrief.disabled = busy;
    btnAsk.disabled = busy;
    btnNew.disabled = busy;
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

  function appendUserTurn(text) {
    chatEmpty.hidden = true;
    const div = document.createElement("div");
    div.className = "chat-turn chat-user";
    div.innerHTML = `<span class="role">You</span><div class="body prose"><p>${escapeHtml(text)}</p></div>`;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
  }

  function appendAssistantTurn(html) {
    const div = document.createElement("div");
    div.className = "chat-turn chat-assistant";
    div.innerHTML = `<span class="role">Advisor</span><div class="body prose">${html}</div>`;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
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

    if (session?.draft?.userHtml) {
      renderExchange(
        session.draft.userHtml,
        session.draft.assistantHtml || "",
        { readOnly: false }
      );
      selectedExchangeId = session.exchangeId ?? null;
      currentStream = session.stream ?? null;
      if (session.pending && !session.draft.assistantHtml) {
        showStatus("Advisor may still be working on this — check back in a moment or pick History.");
      } else {
        hideStatus();
      }
    }

    const items = await loadSidebar();
    if (selectedExchangeId != null) {
      highlightSidebar(selectedExchangeId);
    }

    if (!session) return;

    if (session.exchangeId != null && items.some((item) => item.id === session.exchangeId)) {
      if (!session.draft?.assistantHtml) {
        await selectExchange(session.exchangeId, {
          fromSidebar: session.mode === "view",
          skipPersist: true,
        });
      }
      return;
    }

    if (session.pending && !session.draft?.assistantHtml) {
      const match = items.find((item) => matchesPending(item.preview, session.pending));
      if (match) {
        await selectExchange(match.id, { fromSidebar: false });
      }
    }
  }

  form?.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = questionEl.value.trim();
    if (!q) return;
    clearMainChat();
    chatEmpty.hidden = true;
    appendUserTurn(q);
    questionEl.value = "";
    streamAdvisor("ask", q);
  });

  btnNew?.addEventListener("click", () => {
    clearMainChat();
    hideStatus();
    clearSession();
    questionEl.focus();
  });

  btnBrief?.addEventListener("click", () => {
    clearMainChat();
    chatEmpty.hidden = true;
    const div = document.createElement("div");
    div.className = "chat-turn chat-user";
    div.innerHTML = `<span class="role">You</span><div class="body prose"><p><em>Daily brief</em></p></div>`;
    chat.appendChild(div);
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
