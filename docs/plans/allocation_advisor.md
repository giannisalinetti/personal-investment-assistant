# Plan: Allocation advisor (stated capital)

**Status:** implemented (v1)

## Problem

Users ask how to position a stated amount (e.g. €50k). A raw LLM invents weights and often miscomputes currency amounts. PIA should be more trustworthy than a general SOTA chat.

## Approach

| Piece | Role |
|-------|------|
| Investor preferences | Horizon, risk, currency, UCITS bias in `data/investor_preferences.json` (Settings UI) |
| `compute_allocation` | Deterministic €/$ lines from weights (largest-remainder) |
| `get_risk` / performance | Ground recommended names |
| `portfolio-allocation` skill | Process for allocation asks |

No broker holdings import in v1. No refusal wall — enable and ground.

## Modules

- [`src/investor_preferences.py`](../../src/investor_preferences.py)
- [`src/tools/allocation_tool.py`](../../src/tools/allocation_tool.py)
- Skill [`.agents/skills/portfolio-allocation/SKILL.md`](../../.agents/skills/portfolio-allocation/SKILL.md)

## Non-goals (v1)

- Broker sync / real holdings
- Billing / multi-tenant SaaS
- Deterministic refusal of allocation questions

## Future (not now)

Multi-user / paid platform: replace `data/investor_preferences.json` (and similar per-user JSON on the volume) with a **database or key/value store** keyed by user/account — not shared flat files.
