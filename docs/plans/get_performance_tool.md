# Plan: `get_performance` Advisor tool

## Problem

Questions like “best performing ETF last week” need **period returns**. Today Advisor only has Monitor signals / optional YTD in ticker details and `get_quote` (spot). That gap caused MU (stock) + YTD to be misused as “last week ETF performance.”

Fixes **1+2** (class hard-scope + refuse invented returns) reduce hallucinations but still cannot *answer* the ranking question until a return tool exists.

## Proposed tool

**Name:** `get_performance`  
**Module:** new `src/tools/performance_tool.py` (mirror `src/tools/quote_tool.py`)

```text
get_performance(ticker: str, period: str = "1wk") -> JSON
```

| Field | Meaning |
|-------|---------|
| `ticker` | Yahoo symbol |
| `period` | `1wk` \| `1mo` \| `3mo` \| `ytd` \| `1y` (start with these) |
| `return_pct` | Close-to-close total return over the window |
| `start_price` / `end_price` | Anchors for auditability |
| `start_as_of` / `end_as_of` | Dates used |
| `error` | If history missing |

Implementation: `yfinance` history (reuse cache dir from `src/tools/yfinance_tool.py`); sync fetch + `@tool` wrapper like `get_quote`.

Optional companion (same PR or follow-up):

```text
rank_performance(tickers: list[str], period: str = "1wk", asset_class: str | None = None) -> JSON
```

Returns sorted list by `return_pct` so the model does not need N serial tool calls for “best ETF on my watchlist.” Prefer **one** `rank_performance` for watchlist rankings; keep `get_performance` for single-ticker asks.

## Wire into Advisor

1. Register tools in `src/nodes/advisor.py` `_invoke_advisor_sync`: `[get_quote, get_performance]` (and `rank_performance` if added).
2. System prompt: when `asks_period_performance(question)`, tell the model to **call** `rank_performance` / `get_performance` instead of saying unavailable (caveat block becomes “use the tool”).
3. Respect asset-class scope: if question is ETF-scoped, only pass ETF tickers into `rank_performance` (Python can also filter inside the tool using watchlist + `infer_asset_class_scope`).
4. Docs: extend tools table in `docs/agent_architecture.md`.
5. Tests: unit tests with mocked history; loop test that fake LLM requests `get_performance`.

## Non-goals (v1)

- Intraday / open-market timing precision
- Benchmark-relative alpha
- Changing Monitor graph (stay Advisor-only tools)

## Acceptance

- `/ask what is the best performing ETF last week?` → model calls ranking/performance tool → answer names an **`[etf]`** ticker with a **computed** week return (or explicit tool error), never a stock like MU from signals alone.
