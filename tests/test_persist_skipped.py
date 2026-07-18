"""Unit tests for skipped-run state preservation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.state import initial_state
from src.state_persistence import persist_state, state_to_document


class PersistSkippedStateTests(unittest.TestCase):
    def test_skipped_run_preserves_prior_signals(self) -> None:
        prior = {
            "last_run": "2026-07-17T12:00:00+00:00",
            "run_type": "end_of_day",
            "skipped": False,
            "signals": [
                {
                    "ticker": "AAPL",
                    "signal": "BUY",
                    "confidence": "HIGH",
                    "rationale": "kept",
                    "asset_class": "stock",
                }
            ],
            "suggestions": [{"ticker": "QQQ", "name": "QQQ", "reason": "overlap"}],
            "watchlist_note": "prior note",
            "ticker_details": {"AAPL": {"name": "Apple"}},
            "errors": [],
            "notification_sent": True,
        }
        skipped_state = initial_state([], run_type="pre_market")
        skipped_state["skipped"] = True
        skipped_state["signals"] = []

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            state_path = data_dir / "state.json"
            state_path.write_text(json.dumps(prior), encoding="utf-8")

            with (
                mock.patch("src.state_persistence.DATA_DIR", data_dir),
                mock.patch("src.state_persistence.STATE_PATH", state_path),
                mock.patch("src.state_persistence.STATE_TMP_PATH", data_dir / "state.json.tmp"),
                mock.patch("src.state_persistence.load_watchlist", return_value=[]),
                mock.patch(
                    "src.state_persistence.watchlist_counts",
                    return_value={"stock": 0, "etf": 0, "etc": 0},
                ),
            ):
                persist_state(skipped_state)
                saved = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(saved["skipped"])
        self.assertEqual(saved["run_type"], "pre_market")
        self.assertEqual(saved["signals"], prior["signals"])
        self.assertEqual(saved["suggestions"], prior["suggestions"])
        self.assertEqual(saved["watchlist_note"], "prior note")
        self.assertEqual(saved["ticker_details"], prior["ticker_details"])

    def test_state_to_document_marks_skipped(self) -> None:
        state = initial_state([], run_type="midday")
        state["skipped"] = True
        with (
            mock.patch("src.state_persistence.load_watchlist", return_value=[]),
            mock.patch(
                "src.state_persistence.watchlist_counts",
                return_value={"stock": 0, "etf": 0, "etc": 0},
            ),
        ):
            doc = state_to_document(state)
        self.assertTrue(doc["skipped"])
        self.assertEqual(doc["signals"], [])


if __name__ == "__main__":
    unittest.main()
