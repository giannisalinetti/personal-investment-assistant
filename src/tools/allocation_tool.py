"""Advisor tool: deterministic capital allocation amounts from weights."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_WEIGHT_SUM_TOLERANCE = 0.05
_ALLOWED_CURRENCIES = frozenset({"EUR", "USD"})


def allocate_amounts(amount: float, weight_pcts: list[float]) -> list[float]:
    """Largest-remainder rounding so allocated amounts sum exactly to amount."""
    if amount <= 0 or not weight_pcts:
        return []
    total_cents = int(round(amount * 100))
    exact_cents = [amount * 100.0 * (w / 100.0) for w in weight_pcts]
    floor_cents = [int(x) for x in exact_cents]
    remainder = total_cents - sum(floor_cents)
    order = sorted(
        range(len(exact_cents)),
        key=lambda i: (exact_cents[i] - floor_cents[i], -i),
        reverse=True,
    )
    for k in range(max(0, remainder)):
        floor_cents[order[k % len(order)]] += 1
    return [c / 100.0 for c in floor_cents]


def compute_allocation_payload(
    *,
    amount: float,
    currency: str,
    legs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pure helper used by the tool and unit tests."""
    currency_key = (currency or "EUR").strip().upper()
    if currency_key not in _ALLOWED_CURRENCIES:
        return {
            "ok": False,
            "error": f"currency must be one of {sorted(_ALLOWED_CURRENCIES)}",
        }
    if amount is None or float(amount) <= 0:
        return {"ok": False, "error": "amount must be > 0"}

    amount_f = float(amount)
    if not legs:
        return {"ok": False, "error": "legs must be a non-empty list"}

    cleaned: list[dict[str, Any]] = []
    weights: list[float] = []
    for i, raw in enumerate(legs):
        if not isinstance(raw, dict):
            return {"ok": False, "error": f"legs[{i}] must be an object"}
        ticker = str(raw.get("ticker", "")).strip().upper()
        if not ticker:
            return {"ok": False, "error": f"legs[{i}].ticker is required"}
        try:
            w = float(raw.get("weight_pct"))
        except (TypeError, ValueError):
            return {"ok": False, "error": f"legs[{i}].weight_pct must be a number"}
        if w < 0:
            return {"ok": False, "error": f"legs[{i}].weight_pct must be >= 0"}
        cleaned.append({"ticker": ticker, "weight_pct": w})
        weights.append(w)

    sum_weights = sum(weights)
    if abs(sum_weights - 100.0) > _WEIGHT_SUM_TOLERANCE:
        return {
            "ok": False,
            "error": (
                f"weight_pct must sum to 100 (±{_WEIGHT_SUM_TOLERANCE}); "
                f"got {round(sum_weights, 4)}"
            ),
            "sum_weights": round(sum_weights, 4),
        }

    amounts = allocate_amounts(amount_f, weights)
    out_legs = [
        {
            "ticker": cleaned[i]["ticker"],
            "weight_pct": round(cleaned[i]["weight_pct"], 4),
            "amount": amounts[i],
        }
        for i in range(len(cleaned))
    ]
    sum_amounts = round(sum(amounts), 2)
    return {
        "ok": True,
        "amount": amount_f,
        "currency": currency_key,
        "legs": out_legs,
        "sum_weights": round(sum_weights, 4),
        "sum_amounts": sum_amounts,
    }


@tool
def compute_allocation(amount: float, legs_json: str, currency: str = "EUR") -> str:
    """Compute exact currency amounts from portfolio weight percentages.

    Use when the user asks how to distribute / allocate / position a stated
    capital amount. Pass weights that sum to 100. Cite only the returned
    amounts — never invent euro/dollar line items.

    Args:
        amount: Total capital to allocate (must be > 0).
        legs_json: JSON array of objects with ticker and weight_pct, e.g.
            [{"ticker":"VWCE.DE","weight_pct":40},{"ticker":"QQQ","weight_pct":60}].
        currency: EUR or USD (default EUR).
    """
    try:
        legs = json.loads(legs_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"ok": False, "error": f"invalid legs_json: {exc}"})
    if not isinstance(legs, list):
        return json.dumps({"ok": False, "error": "legs_json must be a JSON array"})

    payload = compute_allocation_payload(amount=amount, currency=currency, legs=legs)
    logger.info(
        "compute_allocation amount=%s currency=%s ok=%s",
        amount,
        currency,
        payload.get("ok"),
    )
    return json.dumps(payload)
