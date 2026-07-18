"""Unit tests for compact Monitor notification formatting."""

from __future__ import annotations

import unittest

from src.nodes.notifier import format_notification


class CompactNotificationTests(unittest.TestCase):
    def test_one_line_per_signal_and_sane_line_count(self) -> None:
        state = {
            "run_type": "pre_market",
            "signals": [
                {
                    "ticker": "AAPL",
                    "signal": "BUY",
                    "confidence": "MEDIUM",
                    "rationale": "RSI oversold with MACD cross confirming a rebound setup today.",
                    "asset_class": "stock",
                },
                {
                    "ticker": "MSFT",
                    "signal": "SELL",
                    "confidence": "HIGH",
                    "rationale": "Extended above upper Bollinger band with fading momentum.",
                    "asset_class": "stock",
                },
                {
                    "ticker": "VWCE.DE",
                    "signal": "WATCH",
                    "confidence": "MEDIUM",
                    "rationale": "EMA flattening near support; wait for confirmation.",
                    "asset_class": "etf",
                },
            ],
            "suggestions": [
                {
                    "ticker": "QQQ",
                    "name": "Invesco QQQ",
                    "reason": "High overlap with mega-cap tech names already on the list.",
                    "asset_class": "etf",
                }
            ],
            "watchlist_note": "Risk-on tone overnight in US futures.",
        }
        body = format_notification(state)
        lines = [line for line in body.splitlines() if line.strip()]

        self.assertLessEqual(len(lines), 12)
        self.assertTrue(any(line.startswith("🟢 AAPL BUY MED") for line in lines))
        self.assertTrue(any(line.startswith("🔴 MSFT SELL HI") for line in lines))
        self.assertTrue(any(line.startswith("🟡 VWCE.DE WATCH MED") for line in lines))
        # Rationale stays on the same signal line (no blank multi-line dump)
        self.assertEqual(sum(1 for line in lines if "AAPL" in line), 1)
        self.assertIn("Not financial advice", body)


if __name__ == "__main__":
    unittest.main()
