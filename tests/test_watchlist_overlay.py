"""Unit tests for watchlist data-volume overlay merge."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.config import WatchlistEntry
from src.watchlist_overlay import (
    clear_class_override,
    load_overlay_raw,
    merge_watchlists,
    parse_entries_payload,
    set_class_override,
)


class WatchlistOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.data_dir = Path(self._tmpdir.name)
        self.overlay = self.data_dir / "watchlists_override.json"
        self.patchers = [
            mock.patch("src.watchlist_overlay.DATA_DIR", self.data_dir),
            mock.patch("src.watchlist_overlay.OVERLAY_PATH", self.overlay),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_merge_replaces_only_overridden_class(self) -> None:
        defaults = [
            WatchlistEntry(ticker="AAPL", name="Apple", asset_class="stock"),
            WatchlistEntry(ticker="QQQ", name="Nasdaq", asset_class="etf"),
            WatchlistEntry(ticker="SPY", name="S&P", asset_class="etf"),
        ]
        overlay = {
            "etf": [{"ticker": "VWCE.DE", "name": "All-World"}],
        }
        merged = merge_watchlists(defaults, overlay)
        tickers = [e.ticker for e in merged]
        self.assertIn("AAPL", tickers)
        self.assertEqual([e.ticker for e in merged if e.asset_class == "etf"], ["VWCE.DE"])
        self.assertNotIn("QQQ", tickers)

    def test_set_and_clear_class_override(self) -> None:
        set_class_override(
            "stock",
            [WatchlistEntry(ticker="IBM", name="IBM", asset_class="stock")],
        )
        raw = load_overlay_raw()
        self.assertEqual(raw["stock"][0]["ticker"], "IBM")
        clear_class_override("stock")
        self.assertEqual(load_overlay_raw(), {})
        self.assertFalse(self.overlay.exists())

    def test_parse_entries_dedupes(self) -> None:
        entries = parse_entries_payload(
            [
                {"ticker": "aapl", "name": "Apple"},
                {"ticker": "AAPL", "name": "Apple Dup"},
                {"ticker": "MSFT", "name": "Microsoft"},
            ],
            "stock",
        )
        self.assertEqual([e.ticker for e in entries], ["AAPL", "MSFT"])

    def test_load_watchlists_applies_overlay(self) -> None:
        self.overlay.write_text(
            json.dumps(
                {
                    "version": 1,
                    "classes": {
                        "etc": [{"ticker": "4GLD.DE", "name": "Gold"}],
                    },
                }
            ),
            encoding="utf-8",
        )
        defaults = [
            WatchlistEntry(ticker="AAPL", name="Apple", asset_class="stock"),
            WatchlistEntry(ticker="GLD", name="Old Gold", asset_class="etc"),
        ]
        with (
            mock.patch("src.watchlist_overlay.load_yaml_defaults", return_value=defaults),
            mock.patch(
                "src.watchlist_overlay.load_overlay_raw",
                return_value={"etc": [{"ticker": "4GLD.DE", "name": "Gold"}]},
            ),
        ):
            from src.watchlist_overlay import load_overlay_raw as lor
            from src.watchlist_overlay import load_yaml_defaults as lyd
            from src.watchlist_overlay import merge_watchlists as mw

            merged = mw(lyd(), lor())
        self.assertEqual([e.ticker for e in merged if e.asset_class == "etc"], ["4GLD.DE"])
        self.assertEqual([e.ticker for e in merged if e.asset_class == "stock"], ["AAPL"])


class WatchlistResetApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.data_dir = Path(self._tmpdir.name)
        self.overlay = self.data_dir / "watchlists_override.json"
        self.patchers = [
            mock.patch("src.watchlist_overlay.DATA_DIR", self.data_dir),
            mock.patch("src.watchlist_overlay.OVERLAY_PATH", self.overlay),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_reset_one_class_keeps_other_overrides(self) -> None:
        from fastapi.testclient import TestClient

        from src.web.app import create_app

        set_class_override(
            "stock",
            [WatchlistEntry(ticker="IBM", name="IBM", asset_class="stock")],
        )
        set_class_override(
            "etf",
            [WatchlistEntry(ticker="QQQ", name="Nasdaq", asset_class="etf")],
        )
        client = TestClient(create_app())
        res = client.post(
            "/api/settings/watchlists/reset",
            json={"asset_class": "etf"},
        )
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertEqual(payload["overridden_classes"], ["stock"])
        self.assertEqual(payload["effective"]["stock"][0]["ticker"], "IBM")
        raw = load_overlay_raw()
        self.assertIn("stock", raw)
        self.assertNotIn("etf", raw)


if __name__ == "__main__":
    unittest.main()
