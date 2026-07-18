# Plan: `get_performance` Advisor tool

**Status:** implemented (v1)

## Problem

Questions like “best performing ETF last week” need **period returns**. Advisor previously only had Monitor signals / optional YTD and `get_quote` (spot). That gap caused MU (stock) + YTD to be misused as “last week ETF performance.”

## Tools (shipped)

**Module:** [`src/tools/performance_tool.py`](../../src/tools/performance_tool.py)

```text
get_performance(ticker: str, period: str = "1wk") -> JSON
rank_performance(tickers: list[str] | None = None, period: str = "1wk", asset_class: str | None = None) -> JSON
```

| Field | Meaning |
|-------|---------|
| `ticker` | Yahoo symbol |
| `period` | `1wk` \| `1mo` \| `3mo` \| `ytd` \| `1y` |
| `return_pct` | Close-to-close total return over the window |
| `start_price` / `end_price` | Anchors for auditability |
| `start_as_of` / `end_as_of` | Dates used |
| `error` | If history missing |

`rank_performance` returns `{period, asset_class, ranked, errors}` sorted by `return_pct` desc. Empty `tickers` + `asset_class` loads that class from the watchlist; with `asset_class` set, out-of-class tickers (e.g. MU on an ETF ask) are dropped.

Registered in `_invoke_advisor_sync` with `get_quote` when `ADVISOR_FETCH_QUOTES=true`. When tools are disabled, period asks still get a deterministic refusal.

## Acceptance

- `/ask what is the best performing ETF last week?` → model calls `rank_performance` → answer names an **`[etf]`** ticker with a **computed** week return (or explicit tool error), never a stock like MU from signals alone.

## Non-goals (still)

- Intraday / open-market timing precision
- Benchmark-relative alpha
- Changing Monitor graph (stay Advisor-only tools)
