"""Unit tests for Advisor asset-class scoping and performance caveats."""

from __future__ import annotations

import unittest

from src.config import WatchlistEntry
from src.nodes.advisor import (
    asks_period_performance,
    filter_entries_by_asset_class,
    filter_state_by_asset_class,
    infer_asset_class_scope,
)


def _entry(ticker: str, asset_class: str, name: str | None = None) -> WatchlistEntry:
    return WatchlistEntry(ticker=ticker, name=name or ticker, asset_class=asset_class)  # type: ignore[arg-type]


class AssetClassScopeTests(unittest.TestCase):
    def test_infer_etf_from_question(self) -> None:
        self.assertEqual(
            infer_asset_class_scope("what is the best performing ETF last week?"),
            "etf",
        )

    def test_infer_stock(self) -> None:
        self.assertEqual(infer_asset_class_scope("Which stock looks oversold?"), "stock")

    def test_infer_none_when_mixed_or_absent(self) -> None:
        self.assertIsNone(infer_asset_class_scope("How is my portfolio looking?"))
        self.assertIsNone(infer_asset_class_scope("Compare my stocks and ETFs"))

    def test_filter_entries_and_state_excludes_stocks_for_etf_scope(self) -> None:
        watchlist = [
            _entry("MU", "stock", "Micron"),
            _entry("QQQ", "etf", "Nasdaq ETF"),
            _entry("SPY", "etf", "S&P ETF"),
        ]
        state = {
            "last_run": "t",
            "run_type": "manual",
            "skipped": False,
            "watchlist_note": None,
            "signals": [
                {"ticker": "MU", "asset_class": "stock", "signal": "BUY"},
                {"ticker": "QQQ", "asset_class": "etf", "signal": "WATCH"},
            ],
            "suggestions": [{"ticker": "MU", "asset_class": "stock"}],
            "errors": [],
        }
        scoped = filter_entries_by_asset_class(watchlist, "etf")
        self.assertEqual([e.ticker for e in scoped], ["QQQ", "SPY"])
        filtered = filter_state_by_asset_class(state, watchlist=watchlist, asset_class="etf")
        self.assertEqual([s["ticker"] for s in filtered["signals"]], ["QQQ"])
        self.assertEqual(filtered["suggestions"], [])


class PeriodPerformanceTests(unittest.TestCase):
    def test_detects_last_week_best_performer(self) -> None:
        self.assertTrue(asks_period_performance("best performing ETF last week"))
        self.assertTrue(asks_period_performance("YTD return for QQQ"))
        self.assertFalse(asks_period_performance("What is AAPL trading at?"))

    def test_unavailable_reply_lists_etfs_not_stocks(self) -> None:
        from src.nodes.advisor import period_performance_unavailable_reply

        watchlist = [
            _entry("MU", "stock", "Micron"),
            _entry("QQQ", "etf", "Nasdaq ETF"),
            _entry("SPY", "etf", "S&P ETF"),
        ]
        reply = period_performance_unavailable_reply(
            question="best performing ETF last week",
            watchlist=watchlist,
        )
        self.assertIn("QQQ", reply)
        self.assertIn("SPY", reply)
        self.assertNotIn("MU", reply)
        self.assertIn("won't invent", reply)

    def test_history_filter_drops_out_of_scope_tickers(self) -> None:
        from src.nodes.advisor import filter_history_for_scope

        watchlist = [
            _entry("MU", "stock"),
            _entry("QQQ", "etf"),
        ]
        history = [
            {"role": "user", "content": "best ETF?"},
            {"role": "assistant", "content": "MU was best with +132% YTD"},
            {"role": "user", "content": "How is QQQ?"},
            {"role": "assistant", "content": "QQQ is mixed"},
        ]
        cleaned = filter_history_for_scope(history, watchlist=watchlist, asset_class="etf")
        self.assertEqual(len(cleaned), 3)
        self.assertTrue(all("MU" not in t["content"] for t in cleaned))

if __name__ == "__main__":
    unittest.main()
