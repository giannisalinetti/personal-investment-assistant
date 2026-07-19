"""Unit tests for capital allocation tool, preferences, and detector/skill."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.config import WatchlistEntry
from src.investor_preferences import (
    default_preferences,
    format_preferences_block,
    load_preferences,
    save_preferences,
)
from src.nodes.advisor import asks_capital_allocation
from src.skills import select_skills
from src.tools.allocation_tool import (
    allocate_amounts,
    compute_allocation,
    compute_allocation_payload,
)


def _entry(ticker: str, asset_class: str = "etf") -> WatchlistEntry:
    return WatchlistEntry(ticker=ticker, name=ticker, asset_class=asset_class)  # type: ignore[arg-type]


class AllocateAmountsTests(unittest.TestCase):
    def test_fifty_thousand_forty_twenty_split(self) -> None:
        amounts = allocate_amounts(50000.0, [40.0, 20.0, 20.0, 20.0])
        self.assertEqual(amounts, [20000.0, 10000.0, 10000.0, 10000.0])
        self.assertAlmostEqual(sum(amounts), 50000.0, places=2)

    def test_rounding_sums_exactly(self) -> None:
        amounts = allocate_amounts(100.0, [33.33, 33.33, 33.34])
        self.assertAlmostEqual(sum(amounts), 100.0, places=2)


class ComputeAllocationPayloadTests(unittest.TestCase):
    def test_ok_payload(self) -> None:
        payload = compute_allocation_payload(
            amount=50000,
            currency="EUR",
            legs=[
                {"ticker": "VWCE.DE", "weight_pct": 40},
                {"ticker": "QQQ", "weight_pct": 20},
                {"ticker": "IBM", "weight_pct": 20},
                {"ticker": "NVDA", "weight_pct": 20},
            ],
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["sum_amounts"], 50000.0)
        by_ticker = {leg["ticker"]: leg["amount"] for leg in payload["legs"]}
        self.assertEqual(by_ticker["VWCE.DE"], 20000.0)
        self.assertEqual(by_ticker["QQQ"], 10000.0)

    def test_rejects_bad_weight_sum(self) -> None:
        payload = compute_allocation_payload(
            amount=1000,
            currency="EUR",
            legs=[
                {"ticker": "A", "weight_pct": 50},
                {"ticker": "B", "weight_pct": 40},
            ],
        )
        self.assertFalse(payload["ok"])
        self.assertIn("sum to 100", payload["error"])

    def test_tool_returns_json(self) -> None:
        raw = compute_allocation.invoke(
            {
                "amount": 1000.0,
                "currency": "EUR",
                "legs_json": json.dumps(
                    [
                        {"ticker": "VWCE.DE", "weight_pct": 60},
                        {"ticker": "QQQ", "weight_pct": 40},
                    ]
                ),
            }
        )
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["sum_amounts"], 1000.0)


class PreferencesTests(unittest.TestCase):
    def test_defaults(self) -> None:
        prefs = default_preferences()
        self.assertEqual(prefs.horizon, "long")
        self.assertEqual(prefs.risk_tolerance, "moderate")
        self.assertEqual(prefs.base_currency, "EUR")
        self.assertTrue(prefs.prefer_ucits)

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "investor_preferences.json"
            with (
                mock.patch("src.investor_preferences.PREFERENCES_PATH", path),
                mock.patch(
                    "src.investor_preferences.PREFERENCES_TMP_PATH",
                    Path(tmp) / "investor_preferences.json.tmp",
                ),
                mock.patch("src.investor_preferences.DATA_DIR", Path(tmp)),
            ):
                saved = save_preferences(
                    {
                        "horizon": "short",
                        "risk_tolerance": "aggressive",
                        "base_currency": "USD",
                        "prefer_ucits": False,
                        "notes": "test",
                    }
                )
                self.assertEqual(saved.horizon, "short")
                loaded = load_preferences()
                self.assertEqual(loaded.risk_tolerance, "aggressive")
                self.assertFalse(loaded.prefer_ucits)
                block = format_preferences_block(loaded)
                self.assertIn("aggressive", block)
                self.assertIn("USD", block)


class CapitalAllocationDetectorTests(unittest.TestCase):
    def test_detects_distribute_capital(self) -> None:
        self.assertTrue(
            asks_capital_allocation("how to distribute a 50000 € investment")
        )
        self.assertTrue(asks_capital_allocation("How should I invest €50,000?"))

    def test_ignores_etf_holdings_allocation(self) -> None:
        self.assertFalse(
            asks_capital_allocation("What is the sector allocation of VWCE?")
        )


class PortfolioAllocationSkillTests(unittest.TestCase):
    def test_skill_activates_for_capital_question(self) -> None:
        skills = select_skills(
            mode="ask",
            question="how to distribute a 50000 € investment on my watchlist",
            watchlist=[_entry("VWCE.DE"), _entry("QQQ")],
        )
        names = {s.name for s in skills}
        self.assertIn("portfolio-allocation", names)


if __name__ == "__main__":
    unittest.main()
