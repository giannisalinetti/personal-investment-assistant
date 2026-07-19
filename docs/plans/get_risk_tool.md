# Plan: ETF / ticker risk metrics (`get_risk`)

**Status:** implemented (v1 + Monitor/dashboard 6mo std/MDD)

## Problem

ETF analysis needs volatility context (std deviation, beta, max drawdown). Those are not in Monitor signals or `get_performance` (returns only).

## Approach

Compute from yfinance daily closes (same family as performance tools). No new data vendor.

| Metric | Definition |
|--------|------------|
| `std_dev_ann_pct` | Annualized std of daily simple returns × √252 |
| `max_drawdown_pct` | Worst peak-to-trough % (negative) |
| `beta` | Cov(r, r_bench) / Var(r_bench); default bench `SPY`, EU listings use `VWCE.DE` if on watchlist |

## Tool (Advisor)

**Module:** [`src/tools/risk_tool.py`](../../src/tools/risk_tool.py) (+ helpers in [`risk_metrics.py`](../../src/tools/risk_metrics.py))

```text
get_risk(ticker: str, period: str = "1y", benchmark: str | None = None) -> JSON
```

Periods: `6mo` \| `1y`. Registered with other Advisor tools when `ADVISOR_FETCH_QUOTES=true`.

Skill [`.agents/skills/etf-analysis/SKILL.md`](../../.agents/skills/etf-analysis/SKILL.md) instructs the model to call `get_risk` for vol/beta/drawdown asks.

## Monitor / dashboard

Each Monitor OHLCV snapshot (`DEFAULT_PERIOD` = `6mo`) also stores `std_dev_ann_pct`, `max_drawdown_pct`, and `risk_window: "6mo"` (no beta — avoids extra benchmark fetches). The dashboard expand panel shows **Vol (6mo)** and **Max DD (6mo)** for `etf` / `etc` rows. Prefer Advisor `get_risk` when you need `1y` or beta.

## Non-goals (v1)

- Beta on the dashboard
- `rank_risk`
- Paid risk APIs / Yahoo `info.beta`
