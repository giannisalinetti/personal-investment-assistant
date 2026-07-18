"""Unit tests for Telegram HTML conversion."""

from __future__ import annotations

import unittest

from src.tools.telegram_format import to_telegram_html, to_telegram_plain


class TelegramHtmlTests(unittest.TestCase):
    def test_bold_and_heading(self) -> None:
        text = "## Stocks\n**AAPL** looks firm"
        html = to_telegram_html(text)
        self.assertIn("<b>Stocks</b>", html)
        self.assertIn("<b>AAPL</b>", html)
        self.assertNotIn("##", html)
        self.assertNotIn("**", html)

    def test_markdown_link_and_bare_url(self) -> None:
        text = "See [Yahoo](https://finance.yahoo.com/quote/AAPL) and https://example.com/x"
        html = to_telegram_html(text)
        self.assertIn('<a href="https://finance.yahoo.com/quote/AAPL">Yahoo</a>', html)
        self.assertIn('<a href="https://example.com/x">https://example.com/x</a>', html)

    def test_escapes_raw_html(self) -> None:
        html = to_telegram_html("Price <script>alert(1)</script> & more")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;", html)

    def test_multiline_preserved(self) -> None:
        html = to_telegram_html("Line one\nLine two")
        self.assertEqual(html.count("\n"), 1)

    def test_inline_code(self) -> None:
        html = to_telegram_html("Use `RSI` filter")
        self.assertIn("<code>RSI</code>", html)

    def test_plain_fallback_escapes(self) -> None:
        plain = to_telegram_plain("a < b & c")
        self.assertEqual(plain, "a &lt; b &amp; c")


if __name__ == "__main__":
    unittest.main()
