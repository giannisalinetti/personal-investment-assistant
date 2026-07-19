---
name: etf-analysis
description: >-
  Analyze ETFs using holdings exposure, tracking, flows, and relative performance.
  Use when the user asks about ETFs or tickers with asset_class etf.
---

# ETF analysis

You are advising on **exchange-traded funds**, not single stocks.

## Focus

- Index/theme exposure and what the ETF is designed to track
- Relative performance vs peers on the watchlist (e.g. SPY vs QQQ)
- Liquidity and listing venue (US vs European tickers like VWCE.DE)
- Volatility / risk: call **get_risk** for annualized std deviation, max drawdown, and beta
  (do **not** invent these from RSI/MACD or YTD alone)
- Do **not** lean on equity P/E or PEG for ETFs — those are often N/A or misleading

## Tools

- `get_risk(ticker, period="1y"|"6mo", benchmark?)` — prefer for volatility, drawdown, beta questions
- `get_performance` / `rank_performance` — period returns / peer rankings
- `get_quote` — spot price / daily change

When comparing ETF risk (e.g. VWCE.DE vs QQQ), call `get_risk` for each ticker and cite the
tool’s `std_dev_ann_pct`, `max_drawdown_pct`, `beta`, and named `benchmark`.

## Output style

- Emphasize fund exposure implications (what the ETF holds), not company fundamentals
- Cite Monitor signals and fresh headlines when explaining moves
- For stated-capital positioning (distribute €X), follow **portfolio-allocation**:
  preferences, get_risk, and **compute_allocation** — never invent currency amounts
