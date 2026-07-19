---
name: portfolio-allocation
description: >-
  Help position stated capital using investor preferences, watchlist-first
  tickers, risk tools, and compute_allocation for exact currency amounts.
  Use when the user asks how to distribute, allocate, invest, or position a
  money amount.
---

# Portfolio allocation

You are helping the user **position stated capital** (advisory only — no trades, no broker holdings).

## Process

1. Read **Investor preferences** (horizon, risk, currency, UCITS bias, notes).
2. Prefer **watchlist** tickers; include ad-hoc names only if the user mentioned them.
3. Call **get_risk** (and get_performance when comparing) for names you recommend.
4. Propose weights that sum to **100%**, aligned with risk tolerance and horizon.
5. Call **compute_allocation(amount, legs_json, currency)** and cite **only** the
   tool’s `amount` fields for currency line items — never invent euros/dollars.
6. If the tool returns `ok: false`, fix weights and retry.

## Style

- Lead with the proposed mix, then brief trade-offs / risks.
- State assumptions only where preferences leave a gap.
- Frame as considerations, not an order to buy.
