"""Unit tests for risk metric helpers and get_risk tool."""

from __future__ import annotations

import json
import unittest
from unittest import mock

import pandas as pd

from src.tools.risk_metrics import (
    annualized_std_pct,
    beta_vs_benchmark,
    compute_risk_metrics,
    daily_simple_returns,
    max_drawdown_pct,
)
from src.tools.risk_tool import get_risk, resolve_benchmark


class RiskMetricsHelpersTests(unittest.TestCase):
    def test_max_drawdown_known_series(self) -> None:
        # 100 → 120 → 90 → 100 → peak 120, trough 90 → MDD = 90/120 - 1 = -25%
        closes = pd.Series(
            [100.0, 120.0, 90.0, 100.0],
            index=pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"]),
        )
        self.assertAlmostEqual(max_drawdown_pct(closes), -25.0, places=4)

    def test_annualized_std_constant_returns(self) -> None:
        # Constant 1% daily return → std ≈ 0, annualized ≈ 0
        closes = pd.Series([100 * (1.01**i) for i in range(30)])
        returns = daily_simple_returns(closes)
        std = annualized_std_pct(returns)
        self.assertIsNotNone(std)
        assert std is not None
        self.assertLess(abs(std), 0.01)

    def test_beta_identical_series_is_one(self) -> None:
        closes = pd.Series([100.0, 101.0, 99.0, 102.0, 103.0, 101.5, 104.0, 105.0])
        returns = daily_simple_returns(closes)
        beta = beta_vs_benchmark(returns, returns)
        self.assertIsNotNone(beta)
        assert beta is not None
        self.assertAlmostEqual(beta, 1.0, places=3)

    def test_compute_risk_metrics_payload(self) -> None:
        closes = pd.Series(
            [100.0, 110.0, 105.0, 120.0, 90.0, 95.0, 100.0, 102.0],
            index=pd.date_range("2025-01-01", periods=8, freq="B"),
        )
        bench = closes * 1.0
        payload = compute_risk_metrics(
            closes,
            benchmark_closes=bench,
            window="1y",
            benchmark="SPY",
        )
        self.assertEqual(payload["window"], "1y")
        self.assertEqual(payload["benchmark"], "SPY")
        self.assertIsNotNone(payload["std_dev_ann_pct"])
        self.assertIsNotNone(payload["max_drawdown_pct"])
        self.assertIsNotNone(payload["beta"])
        self.assertLess(payload["max_drawdown_pct"], 0)

    def test_snapshot_market_row_includes_6mo_risk(self) -> None:
        from src.tools.yfinance_tool import snapshot_market_row

        # 100 → 120 → 90 → 100 → MDD = -25%; non-constant returns → std present
        idx = pd.date_range("2025-01-01", periods=4, freq="B", tz="UTC")
        frame = pd.DataFrame(
            {
                "open": [100.0, 120.0, 90.0, 100.0],
                "high": [101.0, 121.0, 91.0, 101.0],
                "low": [99.0, 119.0, 89.0, 99.0],
                "close": [100.0, 120.0, 90.0, 100.0],
                "volume": [1.0, 1.0, 1.0, 1.0],
            },
            index=idx,
        )
        snap = snapshot_market_row(frame, "QQQ")
        self.assertEqual(snap["risk_window"], "6mo")
        self.assertIn("std_dev_ann_pct", snap)
        self.assertIn("max_drawdown_pct", snap)
        self.assertIsNotNone(snap["std_dev_ann_pct"])
        self.assertAlmostEqual(snap["max_drawdown_pct"], -25.0, places=4)
        self.assertNotIn("beta", snap)


class ResolveBenchmarkTests(unittest.TestCase):
    def test_explicit_benchmark_wins(self) -> None:
        self.assertEqual(resolve_benchmark("QQQ", "IWM"), "IWM")

    def test_us_defaults_to_spy(self) -> None:
        self.assertEqual(resolve_benchmark("QQQ"), "SPY")

    def test_euro_uses_vwce_when_on_watchlist(self) -> None:
        fake = [mock.Mock(ticker="VWCE.DE"), mock.Mock(ticker="QQQ")]
        with mock.patch("src.tools.risk_tool.load_watchlists", return_value=fake):
            self.assertEqual(resolve_benchmark("EQQQ.DE"), "VWCE.DE")

    def test_euro_falls_back_to_spy_without_vwce(self) -> None:
        fake = [mock.Mock(ticker="EQQQ.DE")]
        with mock.patch("src.tools.risk_tool.load_watchlists", return_value=fake):
            self.assertEqual(resolve_benchmark("EQQQ.DE"), "SPY")


class GetRiskToolTests(unittest.TestCase):
    def test_tool_metadata(self) -> None:
        self.assertEqual(get_risk.name, "get_risk")
        self.assertIn("ticker", get_risk.args)

    def test_get_risk_returns_json(self) -> None:
        fake = {
            "ticker": "QQQ",
            "period": "1y",
            "window": "1y",
            "std_dev_ann_pct": 18.5,
            "max_drawdown_pct": -22.1,
            "beta": 1.05,
            "benchmark": "SPY",
            "as_of": "2026-07-18",
            "observations": 250,
        }
        with mock.patch("src.tools.risk_tool._fetch_risk_sync", return_value=fake):
            raw = get_risk.invoke({"ticker": "qqq", "period": "1y"})
        payload = json.loads(raw)
        self.assertEqual(payload["ticker"], "QQQ")
        self.assertAlmostEqual(payload["std_dev_ann_pct"], 18.5)
        self.assertEqual(payload["benchmark"], "SPY")


if __name__ == "__main__":
    unittest.main()
