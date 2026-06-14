"""Optional token auth for the web API and pages."""

from __future__ import annotations

from fastapi import Header, HTTPException, Request

from src.config import settings


def _token_from_request(request: Request) -> str | None:
    header = request.headers.get("X-PIA-Token", "").strip()
    if header:
        return header
    query = request.query_params.get("token", "").strip()
    return query or None


def require_web_token(request: Request) -> None:
    """Raise 401 when PIA_WEB_TOKEN is set and the request token does not match."""
    if not settings.web_auth_required:
        return
    provided = _token_from_request(request)
    expected = settings.PIA_WEB_TOKEN.strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing PIA web token")
