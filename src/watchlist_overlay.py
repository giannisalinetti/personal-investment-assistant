"""Persisted watchlist overrides under data/ (writable volume).

Repo ``watchlists/*.yaml`` stay defaults (often mounted read-only). UI/API edits
write ``data/watchlists_override.json``; ``load_watchlists()`` merges them.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from src.config import (
    ASSET_CLASS_LABELS,
    DEFAULT_RSI_OVERBOUGHT,
    DEFAULT_RSI_OVERSOLD,
    PROJECT_ROOT,
    AssetClass,
    WatchlistAlerts,
    WatchlistEntry,
)

logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"
OVERLAY_PATH = DATA_DIR / "watchlists_override.json"

_CLASS_KEYS: tuple[AssetClass, ...] = ("stock", "etf", "etc")


def overlay_path() -> Path:
    return OVERLAY_PATH


def _entry_to_dict(entry: WatchlistEntry) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ticker": entry.ticker.strip().upper(),
        "name": entry.name.strip() or entry.ticker.strip().upper(),
    }
    alerts = entry.alerts
    if (
        alerts.rsi_oversold != DEFAULT_RSI_OVERSOLD
        or alerts.rsi_overbought != DEFAULT_RSI_OVERBOUGHT
    ):
        payload["alerts"] = {
            "rsi_oversold": alerts.rsi_oversold,
            "rsi_overbought": alerts.rsi_overbought,
        }
    return payload


def _dict_to_entry(raw: dict[str, Any], asset_class: AssetClass) -> WatchlistEntry:
    data = dict(raw)
    data["asset_class"] = asset_class
    ticker = str(data.get("ticker", "")).strip().upper()
    data["ticker"] = ticker
    if not data.get("name"):
        data["name"] = ticker
    return WatchlistEntry.model_validate(data)


def load_overlay_raw() -> dict[str, list[dict[str, Any]]]:
    """Return overridden classes only (missing key = use YAML defaults)."""
    if not OVERLAY_PATH.exists():
        return {}
    try:
        with OVERLAY_PATH.open(encoding="utf-8") as handle:
            raw = json.load(handle) or {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read watchlist overlay %s: %s", OVERLAY_PATH, exc)
        return {}

    classes = raw.get("classes")
    if not isinstance(classes, dict):
        # Back-compat: top-level stock/etf/etc keys
        classes = {k: raw[k] for k in _CLASS_KEYS if k in raw}

    out: dict[str, list[dict[str, Any]]] = {}
    for asset_class in _CLASS_KEYS:
        items = classes.get(asset_class)
        if items is None:
            continue
        if not isinstance(items, list):
            logger.warning("Overlay class %s is not a list; ignoring", asset_class)
            continue
        parsed: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("ticker"):
                continue
            try:
                entry = _dict_to_entry(item, asset_class)
                parsed.append(_entry_to_dict(entry))
            except Exception as exc:
                logger.warning("Skip invalid overlay entry %s: %s", item, exc)
        out[asset_class] = parsed
    return out


def save_overlay_raw(classes: dict[str, list[dict[str, Any]]]) -> None:
    """Atomically write overlay. Empty ``classes`` removes the file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not classes:
        if OVERLAY_PATH.exists():
            OVERLAY_PATH.unlink()
            logger.info("Removed watchlist overlay (using YAML defaults)")
        return

    payload = {"version": 1, "classes": classes}
    fd, tmp_name = tempfile.mkstemp(prefix="watchlists_override.", suffix=".tmp", dir=DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_name, OVERLAY_PATH)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    logger.info("Saved watchlist overlay for classes: %s", ", ".join(sorted(classes)))


def overridden_classes() -> list[AssetClass]:
    return [c for c in _CLASS_KEYS if c in load_overlay_raw()]  # type: ignore[misc]


def set_class_override(asset_class: AssetClass, entries: list[WatchlistEntry]) -> None:
    """Replace one asset class in the overlay (full list for that class)."""
    if asset_class not in _CLASS_KEYS:
        raise ValueError(f"unsupported asset_class {asset_class!r}")
    current = load_overlay_raw()
    current[asset_class] = [_entry_to_dict(e) for e in entries]
    # Deduplicate by ticker within class
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in current[asset_class]:
        key = item["ticker"].upper()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    current[asset_class] = deduped
    save_overlay_raw(current)


def clear_class_override(asset_class: AssetClass | None = None) -> None:
    """Clear one class or the entire overlay."""
    if asset_class is None:
        save_overlay_raw({})
        return
    if asset_class not in _CLASS_KEYS:
        raise ValueError(f"unsupported asset_class {asset_class!r}")
    current = load_overlay_raw()
    current.pop(asset_class, None)
    save_overlay_raw(current)


def load_yaml_defaults(directory: Path | None = None) -> list[WatchlistEntry]:
    """Load watchlists from YAML only (no overlay)."""
    from src.config import (
        ASSET_CLASS_FILES,
        DEFAULT_WATCHLIST_PATH,
        WATCHLISTS_DIR,
        _load_legacy_watchlist,
        _parse_class_file,
    )

    watchlists_dir = directory or WATCHLISTS_DIR
    entries: list[WatchlistEntry] = []
    if watchlists_dir.is_dir():
        for asset_class, filename in ASSET_CLASS_FILES.items():
            entries.extend(_parse_class_file(watchlists_dir / filename, asset_class))
    if not entries and DEFAULT_WATCHLIST_PATH.exists():
        entries = _load_legacy_watchlist(DEFAULT_WATCHLIST_PATH)
    return entries


def merge_watchlists(
    defaults: list[WatchlistEntry],
    overlay: dict[str, list[dict[str, Any]]] | None = None,
) -> list[WatchlistEntry]:
    """Apply per-class full replacement from overlay onto YAML defaults."""
    overlay = overlay if overlay is not None else load_overlay_raw()
    by_class: dict[AssetClass, list[WatchlistEntry]] = {
        "stock": [],
        "etf": [],
        "etc": [],
    }
    for entry in defaults:
        by_class[entry.asset_class].append(entry)

    for asset_class in _CLASS_KEYS:
        if asset_class not in overlay:
            continue
        by_class[asset_class] = [
            _dict_to_entry(item, asset_class) for item in overlay[asset_class]
        ]

    merged: list[WatchlistEntry] = []
    for asset_class in _CLASS_KEYS:
        merged.extend(by_class[asset_class])
    return merged


def entries_by_class_payload(entries: list[WatchlistEntry]) -> dict[str, list[dict[str, Any]]]:
    payload: dict[str, list[dict[str, Any]]] = {c: [] for c in _CLASS_KEYS}
    for entry in entries:
        payload[entry.asset_class].append(_entry_to_dict(entry))
    return payload


def settings_snapshot() -> dict[str, Any]:
    """Payload for GET /api/settings/watchlists."""
    defaults = load_yaml_defaults()
    overlay = load_overlay_raw()
    effective = merge_watchlists(defaults, overlay)
    try:
        overlay_rel = str(OVERLAY_PATH.relative_to(PROJECT_ROOT))
    except ValueError:
        overlay_rel = str(OVERLAY_PATH)
    return {
        "overlay_path": overlay_rel,
        "overridden_classes": list(overlay.keys()),
        "labels": dict(ASSET_CLASS_LABELS),
        "defaults": entries_by_class_payload(defaults),
        "effective": entries_by_class_payload(effective),
    }


def parse_entries_payload(
    items: list[dict[str, Any]],
    asset_class: AssetClass,
) -> list[WatchlistEntry]:
    """Validate API/UI entry list for one class."""
    entries: list[WatchlistEntry] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker", "")).strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        name = str(item.get("name", "")).strip() or ticker
        alerts_raw = item.get("alerts")
        if isinstance(alerts_raw, dict):
            alerts = WatchlistAlerts.model_validate(alerts_raw)
        else:
            alerts = WatchlistAlerts()
        entries.append(
            WatchlistEntry(
                ticker=ticker,
                name=name,
                asset_class=asset_class,
                alerts=alerts,
            )
        )
    return entries
