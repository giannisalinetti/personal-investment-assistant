"""Unit tests for get_quote / performance tools and Advisor tool loop."""

from __future__ import annotations

import json
import unittest
from unittest import mock

import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.advisor_tool_loop import invoke_with_tools
from src.config import WatchlistEntry
from src.tools.performance_tool import get_performance, rank_performance
from src.tools.quote_tool import get_quote


class GetQuoteToolTests(unittest.TestCase):
    def test_tool_metadata(self) -> None:
        self.assertEqual(get_quote.name, "get_quote")
        self.assertIn("ticker", get_quote.args)

    def test_get_quote_returns_json(self) -> None:
        fake = {
            "ticker": "AAPL",
            "price": 190.0,
            "change_pct": 1.2,
            "volume": 1000,
            "currency": "USD",
            "as_of": "2026-07-18T12:00:00+00:00",
        }
        with mock.patch("src.tools.quote_tool._fetch_quote_sync", return_value=fake):
            raw = get_quote.invoke({"ticker": "aapl"})
        payload = json.loads(raw)
        self.assertEqual(payload["ticker"], "AAPL")
        self.assertEqual(payload["price"], 190.0)


class PerformanceToolTests(unittest.TestCase):
    def test_tool_metadata(self) -> None:
        self.assertEqual(get_performance.name, "get_performance")
        self.assertIn("ticker", get_performance.args)
        self.assertIn("period", get_performance.args)
        self.assertEqual(rank_performance.name, "rank_performance")

    def test_get_performance_from_closes(self) -> None:
        closes = pd.Series(
            [100.0, 105.0],
            index=pd.to_datetime(["2026-07-10", "2026-07-17"]),
        )
        with mock.patch(
            "src.tools.performance_tool._fetch_history_closes",
            return_value=closes,
        ):
            raw = get_performance.invoke({"ticker": "qqq", "period": "1wk"})
        payload = json.loads(raw)
        self.assertEqual(payload["ticker"], "QQQ")
        self.assertEqual(payload["period"], "1wk")
        self.assertAlmostEqual(payload["return_pct"], 5.0)
        self.assertEqual(payload["start_as_of"], "2026-07-10")
        self.assertEqual(payload["end_as_of"], "2026-07-17")

    def test_get_performance_unsupported_period(self) -> None:
        raw = get_performance.invoke({"ticker": "QQQ", "period": "2wk"})
        payload = json.loads(raw)
        self.assertIn("error", payload)

    def test_rank_performance_sorts_and_filters_asset_class(self) -> None:
        watchlist = [
            WatchlistEntry(ticker="MU", name="Micron", asset_class="stock"),
            WatchlistEntry(ticker="QQQ", name="Nasdaq", asset_class="etf"),
            WatchlistEntry(ticker="SPY", name="S&P", asset_class="etf"),
        ]

        def fake_perf(ticker: str, period: str) -> dict:
            returns = {"QQQ": 2.0, "SPY": 5.0, "MU": 99.0}
            return {
                "ticker": ticker,
                "period": period,
                "return_pct": returns[ticker],
                "start_price": 100.0,
                "end_price": 100.0 + returns[ticker],
                "start_as_of": "2026-07-10",
                "end_as_of": "2026-07-17",
            }

        with (
            mock.patch("src.tools.performance_tool.load_watchlists", return_value=watchlist),
            mock.patch(
                "src.tools.performance_tool._fetch_performance_sync",
                side_effect=fake_perf,
            ),
        ):
            raw = rank_performance.invoke(
                {
                    "tickers": ["MU", "QQQ", "SPY"],
                    "period": "1wk",
                    "asset_class": "etf",
                }
            )
        payload = json.loads(raw)
        self.assertEqual(payload["asset_class"], "etf")
        self.assertEqual([r["ticker"] for r in payload["ranked"]], ["SPY", "QQQ"])
        self.assertNotIn("MU", [r["ticker"] for r in payload["ranked"]])

    def test_rank_performance_loads_watchlist_when_tickers_empty(self) -> None:
        watchlist = [
            WatchlistEntry(ticker="QQQ", name="Nasdaq", asset_class="etf"),
            WatchlistEntry(ticker="SPY", name="S&P", asset_class="etf"),
            WatchlistEntry(ticker="AAPL", name="Apple", asset_class="stock"),
        ]

        def fake_perf(ticker: str, period: str) -> dict:
            return {
                "ticker": ticker,
                "period": period,
                "return_pct": 1.0 if ticker == "QQQ" else 3.0,
                "start_price": 100.0,
                "end_price": 101.0,
                "start_as_of": "2026-07-10",
                "end_as_of": "2026-07-17",
            }

        with (
            mock.patch("src.tools.performance_tool.load_watchlists", return_value=watchlist),
            mock.patch(
                "src.tools.performance_tool._fetch_performance_sync",
                side_effect=fake_perf,
            ),
        ):
            raw = rank_performance.invoke({"period": "1wk", "asset_class": "etf"})
        payload = json.loads(raw)
        self.assertEqual([r["ticker"] for r in payload["ranked"]], ["SPY", "QQQ"])


class AdvisorToolLoopTests(unittest.TestCase):
    def test_loop_executes_tool_then_final_answer(self) -> None:
        class FakeLLM:
            def __init__(self) -> None:
                self.calls = 0
                self.saw_tool_message = False

            def bind_tools(self, tools):
                return self

            def invoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "get_quote",
                                "args": {"ticker": "AAPL"},
                                "id": "call_1",
                                "type": "tool_call",
                            }
                        ],
                    )
                self.saw_tool_message = any(isinstance(m, ToolMessage) for m in messages)
                return AIMessage(content="AAPL is around 190 USD.")

        fake_tool = mock.Mock()
        fake_tool.name = "get_quote"
        fake_tool.invoke.return_value = '{"ticker":"AAPL","price":190.0}'

        llm = FakeLLM()
        answer = invoke_with_tools(
            llm,
            system="sys",
            user="What is AAPL trading at?",
            tools=[fake_tool],
        )
        self.assertIn("190", answer)
        self.assertTrue(llm.saw_tool_message)
        fake_tool.invoke.assert_called_once()

    def test_loop_executes_rank_performance(self) -> None:
        class FakeLLM:
            def __init__(self) -> None:
                self.calls = 0
                self.saw_tool_message = False

            def bind_tools(self, tools):
                return self

            def invoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "rank_performance",
                                "args": {"asset_class": "etf", "period": "1wk"},
                                "id": "call_rank",
                                "type": "tool_call",
                            }
                        ],
                    )
                self.saw_tool_message = any(isinstance(m, ToolMessage) for m in messages)
                return AIMessage(content="SPY led ETFs last week at +5.0%.")

        fake_tool = mock.Mock()
        fake_tool.name = "rank_performance"
        fake_tool.invoke.return_value = json.dumps(
            {
                "period": "1wk",
                "asset_class": "etf",
                "ranked": [{"ticker": "SPY", "return_pct": 5.0}],
                "errors": [],
            }
        )

        answer = invoke_with_tools(
            FakeLLM(),
            system="sys",
            user="best performing ETF last week?",
            tools=[fake_tool],
        )
        self.assertIn("SPY", answer)
        fake_tool.invoke.assert_called_once()

    def test_bind_tools_failure_falls_back(self) -> None:
        class PlainLLM:
            def bind_tools(self, tools):
                raise RuntimeError("no tools")

            def invoke(self, messages):
                assert isinstance(messages[0], SystemMessage)
                assert isinstance(messages[1], HumanMessage)
                return AIMessage(content="plain answer")

        answer = invoke_with_tools(
            PlainLLM(),
            system="sys",
            user="hi",
            tools=[get_quote],
        )
        self.assertEqual(answer, "plain answer")


if __name__ == "__main__":
    unittest.main()
