"""Unit tests for get_quote tool and Advisor tool loop."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.advisor_tool_loop import invoke_with_tools
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
