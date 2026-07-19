"""Persisted investor preferences for Advisor allocation guidance."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"
PREFERENCES_PATH = DATA_DIR / "investor_preferences.json"
PREFERENCES_TMP_PATH = DATA_DIR / "investor_preferences.json.tmp"

Horizon = Literal["short", "medium", "long"]
RiskTolerance = Literal["conservative", "moderate", "aggressive"]
BaseCurrency = Literal["EUR", "USD"]

HORIZON_LABELS: dict[str, str] = {
    "short": "<3 years",
    "medium": "3–10 years",
    "long": "10+ years",
}
RISK_LABELS: dict[str, str] = {
    "conservative": "Conservative",
    "moderate": "Moderate",
    "aggressive": "Aggressive",
}


class InvestorPreferences(BaseModel):
    horizon: Horizon = "long"
    risk_tolerance: RiskTolerance = "moderate"
    base_currency: BaseCurrency = "EUR"
    prefer_ucits: bool = True
    notes: str = Field(default="", max_length=500)

    @field_validator("notes", mode="before")
    @classmethod
    def _notes_str(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()[:500]


def preferences_path() -> Path:
    return PREFERENCES_PATH


def default_preferences() -> InvestorPreferences:
    return InvestorPreferences()


def load_preferences() -> InvestorPreferences:
    """Load preferences from disk, or defaults if missing/invalid."""
    if not PREFERENCES_PATH.exists():
        return default_preferences()
    try:
        raw = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read investor preferences: %s", exc)
        return default_preferences()
    if not isinstance(raw, dict):
        return default_preferences()
    try:
        return InvestorPreferences.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 — fall back to defaults
        logger.warning("Invalid investor preferences, using defaults: %s", exc)
        return default_preferences()


def save_preferences(prefs: InvestorPreferences | dict[str, Any]) -> InvestorPreferences:
    """Validate and atomically persist preferences."""
    model = (
        prefs
        if isinstance(prefs, InvestorPreferences)
        else InvestorPreferences.model_validate(prefs)
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(model.model_dump(), indent=2, ensure_ascii=False) + "\n"
    PREFERENCES_TMP_PATH.write_text(payload, encoding="utf-8")
    os.replace(PREFERENCES_TMP_PATH, PREFERENCES_PATH)
    logger.info("Persisted investor preferences to %s", PREFERENCES_PATH)
    return model


def format_preferences_block(prefs: InvestorPreferences | None = None) -> str:
    """Compact prompt block for Advisor."""
    p = prefs or load_preferences()
    notes = p.notes.strip() or "(none)"
    return (
        f"horizon: {p.horizon} ({HORIZON_LABELS.get(p.horizon, p.horizon)})\n"
        f"risk_tolerance: {p.risk_tolerance} "
        f"({RISK_LABELS.get(p.risk_tolerance, p.risk_tolerance)})\n"
        f"base_currency: {p.base_currency}\n"
        f"prefer_ucits: {p.prefer_ucits}\n"
        f"notes: {notes}"
    )
