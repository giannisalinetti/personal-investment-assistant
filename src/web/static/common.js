/** Shared helpers — persist optional PIA_WEB_TOKEN from URL for API calls. */
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
})();
