/** Shared helpers — auth token + theme toggle. */
(function () {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token");
  if (token) {
    sessionStorage.setItem("pia_web_token", token);
  }

  window.piaAuthHeaders = function () {
    const stored = sessionStorage.getItem("pia_web_token");
    if (!stored) return {};
    return { "X-PIA-Token": stored };
  };

  window.piaTokenQuery = function () {
    const stored = sessionStorage.getItem("pia_web_token");
    return stored ? `?token=${encodeURIComponent(stored)}` : "";
  };

  const THEME_KEY = "pia-theme";

  function currentTheme() {
    const attr = document.documentElement.getAttribute("data-theme");
    if (attr === "dark" || attr === "light") return attr;
    try {
      const stored = localStorage.getItem(THEME_KEY);
      if (stored === "dark" || stored === "light") return stored;
    } catch (_) {
      /* ignore */
    }
    return "light";
  }

  function applyTheme(theme) {
    const next = theme === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch (_) {
      /* ignore */
    }
    const btn = document.getElementById("theme-toggle");
    if (btn) {
      btn.textContent = next === "dark" ? "Light" : "Night";
      btn.setAttribute("aria-label", next === "dark" ? "Switch to light mode" : "Switch to night mode");
    }
  }

  window.piaApplyTheme = applyTheme;

  document.addEventListener("DOMContentLoaded", function () {
    applyTheme(currentTheme());
    const btn = document.getElementById("theme-toggle");
    if (btn) {
      btn.addEventListener("click", function () {
        applyTheme(currentTheme() === "dark" ? "light" : "dark");
      });
    }
  });
})();
