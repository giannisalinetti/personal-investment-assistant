# Personal Investment Assistant — Project Specification

## Overview

An autonomous **advisory-only** personal assistant built with **LangGraph** that monitors a user-defined watchlist of stocks and ETFs, performs technical and news-driven analysis, and helps the user **make informed decisions** — not just receive ticker alerts.

The agent has **no access to the user's portfolio** — no holdings, balances, cost basis, or broker integration. It reasons only over the watchlist in `watchlist.yaml` and public market data. All output is advisory; the user decides whether to act.

**Two operating modes:**

| Mode | Trigger | LLM reasoning | Purpose |
|---|---|---|---|
| **Monitor** | Scheduled runs (08:00 / 13:00 / 17:30) + manual `pia-graph` | Off — fast structured calls | Detect changes, score news, emit alerts |
| **Advisor** | On demand — Telegram `/ask`, `/brief`, or CLI | On — deliberate multi-step analysis | Help interpret signals, resolve conflicts, explore scenarios |

Scheduled runs **inform** ("something changed on AAPL"). Advisor mode **deliberates** ("technical says BUY but news is negative — here's how to think about it"). Both modes share the same data foundation (`data/state.json`, watchlist, market snapshots).

**LangGraph** orchestrates the Monitor pipeline. Advisor interactions use a separate reasoning path fed by persisted run state — see [Advisor Mode](#advisor-mode-on-demand-reasoning).

### Roadmap

| Phase | Focus | Status |
|---|---|---|
| **1** | Monitor pipeline (LangGraph, signals, notifications) | ✅ Complete |
| **Deployment** | `pia-run` timers, `pia-console`, deploy templates | ✅ Templates ready — install when project is complete |
| **2** | Advisor mode (CLI, Telegram, reasoning, fresh news, useful links) | ✅ Complete |
| **3** | Production Advisor (persisted memory, proactive brief, live quotes, valuation metrics, scans, `pia-bot` install scripts) | ✅ Complete |
| **4** | Browser web app (dashboard + advisor chat) | Planned |

---

## Goals

**Monitor mode (scheduled pipeline)**

- Monitor a user-defined watchlist of stocks and ETFs
- Suggest additional correlated instruments not in the watchlist
- Compute technical indicators (RSI, MACD, moving averages)
- Fetch and interpret relevant financial news and sentiment
- Generate buy/sell/hold/watch signals and **watchlist comparison notes** (relative performance among monitored symbols)
- Deliver notifications via Telegram bot and/or email
- Run autonomously on a schedule without manual intervention
- Provide a live terminal console for local monitoring

**Advisor mode (on demand)**

- Explain macro context **for the user's watchlist** — not generic market commentary
- Resolve conflicts between technical signals and news sentiment
- Run scenario analysis ("what if rates stay high for 6 months?") with assumptions stated explicitly
- Answer follow-up questions in natural language via Telegram or CLI
- Produce a daily **`/brief`** — macro picture, top conflicts, and what to watch today

**Operational**

- Provide a simple way to stop the advisor daemon gracefully at any time (`/stop`)

**Phase 3 (complete)**

- Remember conversation context across Advisor restarts (`data/advisor/history.json`, `/clear`)
- Deliver a proactive morning brief after the pre-market Monitor run (`PROACTIVE_BRIEF_*` flags)
- Fetch live quotes on demand when answering Advisor questions
- Fetch valuation metrics on demand (trailing P/E, forward P/E, PEG) — Advisor only, not Monitor
- Ad-hoc ticker analysis and indicator scans for symbols/comparisons outside the watchlist
- Install scripts for `pia-bot` (`deploy/install-pia-bot-macos.sh`, `deploy/install-pia-bot-linux.sh`) — run after local validation

**Phase 4 (planned)**

- Use Monitor dashboard and Advisor chat in a local web browser (`pia-web`)

## Non-Goals

- No real-money trading execution (read/analyze only)
- No portfolio tracking, holdings import, or position sizing — advisory over watchlist only
- No backtesting engine (v1)
- No web UI until **Phase 4** (terminal console and Telegram until then)
- No external LLM API calls — fully local inference via Ollama
- No multi-user or cloud-hosted SaaS — single-user, local-first (Phase 4 web app binds to localhost by default)

---

## Architecture

### Two modes, one assistant

```
┌─────────────────────────────────────────────────────────────────┐
│  MONITOR MODE — scheduled / pia-graph / pia-run                 │
│  reasoning OFF · fast · 3 LLM calls per run                     │
├─────────────────────────────────────────────────────────────────┤
│  Supervisor → [Market Data | News | Discovery] → Analyst → Notify │
│                              │                                   │
│                              ▼                                   │
│                     data/state.json (atomic write)               │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  ADVISOR MODE — on demand · main.py daemon or CLI               │
│  reasoning ON · slower · user-triggered only                      │
├─────────────────────────────────────────────────────────────────┤
│  Load state.json + watchlist + user question                    │
│       → Advisor node (LLM with reasoning=True)                  │
│       → Telegram reply / CLI output                             │
│  Commands: /brief  /ask  /status  /stop                         │
└─────────────────────────────────────────────────────────────────┘

[Console — src/console.py]
(separate process, reads state.json, read-only)
```

Monitor mode runs unattended on a schedule. Advisor mode runs only when the user asks — it reads the latest persisted run as context and uses **reasoning** to produce deliberative, decision-oriented output.

### Monitor pipeline (LangGraph)

```
[Scheduler / Entry Point — pia-run | pia-graph]
         │
         ▼
[Supervisor Node]
    ├──────────────────────┬─────────────────────┐
    ▼                      ▼                     ▼
[Market Data Node]    [News Analyst Node]   [Discovery Node]
(prices, indicators)  (headlines, sentiment) (correlated instruments)
    └──────────────────────┴─────────────────────┘
                           │
                           ▼
               [Analyst Node]
               (rule-based signals + LLM rationale polish + watchlist note)
                           │
                           ▼
               [Notifier Node]
               (Telegram + Email dispatch)
                           │
                           ▼
               [state.json — atomic persist]
```

### Supervisor Node

The graph entry point. Runs before any parallel work:

1. Load watchlist from `watchlist.yaml`
2. Check market calendar — if all relevant exchanges are closed, set a skip flag and route to Notifier (no-op) or exit early
3. Initialise `AgentState` with `run_timestamp` and empty collections
4. Fan out to **Market Data**, **News Analyst**, and **Discovery** in parallel (LangGraph parallel edges)
5. Join when all three complete, then route to **Analyst Node**

No LLM calls in the Supervisor — orchestration and gating only.

### LLM vs rules

**Monitor mode — reasoning OFF**

| Responsibility | Implementation |
|---|---|
| RSI, MACD, EMA, Bollinger signals | Rule-based (`indicators.py`) |
| Signal strength and BUY/SELL/HOLD/WATCH | Rule-based (`analyst.py`) |
| News sentiment (-1.0 to +1.0) | LLM, one batched call (`news_analyst.py`) |
| Correlated instrument suggestions | LLM, one call (`discovery.py`), validated against yfinance |
| Human-readable rationale in notifications | LLM polish, notifiable signals only (`analyst.py`) |
| Watchlist comparison note (YTD) | Computed from market data; LLM may rephrase |

Keep deterministic logic in code. In Monitor mode the LLM handles **classification and language only** — no chain-of-thought reasoning.

**Advisor mode — reasoning ON**

| Responsibility | Implementation |
|---|---|
| Macro picture for watchlist | LLM with reasoning (`advisor.py`) |
| Technical vs news conflict resolution | LLM with reasoning |
| Scenario / what-if analysis | LLM with reasoning |
| Free-form follow-up questions | LLM with reasoning + conversation context |
| Daily brief (`/brief`) | LLM with reasoning over latest `state.json` |

Advisor output is **deliberative narrative** — trade-offs, assumptions, and context — not a buy/sell order. Facts (signals, scores, prices) come from Monitor state; the LLM interprets them.

**What stays rule-based in both modes:** signal assignment, notification gating, ticker validation, market calendar skips, watchlist edits.

### State Schema

```python
class AgentState(TypedDict):
    watchlist: list[str]           # user-defined ticker symbols
    discovered: list[dict]         # correlated instruments suggested by Discovery node
    market_data: dict              # raw OHLCV + indicators per ticker (watchlist only)
    news_items: list[dict]         # headlines, source, sentiment score
    signals: list[dict]            # per-ticker signals with rationale
    suggestions: list[dict]        # discovery output (validated tickers)
    watchlist_note: str | None     # optional cross-ticker comparison (no holdings)
    notification_sent: bool
    run_timestamp: str
    run_type: str                  # "pre_market" | "midday" | "end_of_day"
    skipped: bool                  # True if market closed
    errors: list[str]              # non-fatal errors to include in report
```

---

## Tech Stack

| Layer | Tool | Notes |
|---|---|---|
| Agent framework | LangGraph | Graph-based state machine |
| LLM | Ollama | 100% local — no external API calls |
| Market data | `yfinance` | Free, no API key required |
| Technical indicators | `pandas-ta` | RSI, MACD, EMA, Bollinger Bands |
| Market calendar | `pandas_market_calendars` | NYSE + XETRA (v1); skip when all watchlist exchanges closed |
| HTTP (async) | `httpx` | RSS fetch and other async I/O |
| News / sentiment | `feedparser` + RSS | Configurable feeds; watchlist Google News added at runtime |
| Telegram | `python-telegram-bot` | Async bot API v21+ |
| Email | `smtplib` + `email` stdlib | Gmail SMTP or SendGrid |
| Scheduling (v1 deploy) | launchd (macOS) / systemd timers (Linux) | One-shot Monitor runs — see Service Lifecycle |
| Scheduling + Advisor | `APScheduler` in `main.py` | Long-running daemon: scheduled runs + Telegram advisor commands |
| Terminal console | `rich` | Live dashboard, read-only, separate process |
| Config | `pydantic-settings` + `.env` | Typed configuration |
| Package manager | `uv` | Isolated `.venv` per project, Python 3.12+ |
| Runtime | **macOS or Linux** | Local execution; primary dev target macOS (Apple Silicon) |

### Platform notes

| Platform | Ollama inference | Scheduled runs |
|---|---|---|
| **macOS** | Metal (Apple Silicon GPU) | launchd calendar intervals → one-shot `pia-run` |
| **Linux** | CUDA / ROCm / CPU (host-dependent) | systemd user timers → one-shot `pia-run.service` |

The Python application code is OS-agnostic. Platform differences are limited to deployment templates under `deploy/`.

### Environment Isolation

`uv` creates an isolated `.venv` inside the project folder — nothing touches the system Python.

```bash
uv init personal-investment-assistant && cd personal-investment-assistant
uv add langgraph langchain-core langchain-ollama yfinance pandas-ta \
       pandas-market-calendars feedparser python-telegram-bot \
       apscheduler pydantic-settings pyyaml rich httpx
uv run pia-graph                 # manual Monitor run (development)
uv run pia-run --run-type manual # scheduled Monitor entry point
uv run python src/console.py     # console (separate terminal)
uv run pia-advisor               # interactive advisor CLI (phase 2)
uv run pia-bot                   # long-running daemon: Telegram (phase 2)
uv run pia-web                   # browser UI (phase 4)
```

---

## LLM — Interchangeable Model

The model is configured via `.env` and never hardcoded. All LLM access goes through `src/llm.py` — the **only** place where `ChatOllama` is instantiated.

Two factory functions separate Monitor speed from Advisor depth:

```python
# src/llm.py
from langchain_ollama import ChatOllama
from src.config import settings

def get_llm(temperature: float = 0.1) -> ChatOllama:
    """Monitor pipeline — reasoning OFF, small context, short output."""
    return ChatOllama(
        model=settings.OLLAMA_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=temperature,
        reasoning=False,
        num_ctx=settings.OLLAMA_NUM_CTX,
        num_predict=settings.OLLAMA_NUM_PREDICT,
    )

def get_advisor_llm(temperature: float = 0.3) -> ChatOllama:
    """Advisor mode — reasoning ON, larger context for deliberation."""
    return ChatOllama(
        model=settings.OLLAMA_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=temperature,
        reasoning=True,
        num_ctx=settings.OLLAMA_ADVISOR_NUM_CTX,
        num_predict=settings.OLLAMA_ADVISOR_NUM_PREDICT,
    )
```

| Setting | Monitor default | Advisor default | Purpose |
|---|---|---|---|
| `reasoning` | `False` | `True` | Chain-of-thought for on-demand analysis only |
| `num_ctx` | `8192` | `16384` | KV cache size — keep Monitor small for speed |
| `num_predict` | `512` | `4096` | Monitor returns JSON; Advisor returns prose |

To swap models, edit `.env` only — no code changes:

```bash
OLLAMA_MODEL=qwen3:8b     # default — fast Monitor runs, capable Advisor with reasoning
# OLLAMA_MODEL=qwen3:14b  # better Advisor quality, ~10GB VRAM
# OLLAMA_MODEL=qwen3:32b  # best Advisor quality, ~22GB VRAM
# OLLAMA_MODEL=qwen2.5:7b # stable fallback if Qwen3 issues
```

**Never instantiate `ChatOllama` outside `src/llm.py`.**  
**Never enable reasoning in Monitor pipeline nodes** (`news_analyst`, `discovery`, `analyst`).

---

## Project Structure

```
Personal-Investment-Assistant/
├── pyproject.toml                # uv-managed dependencies
├── .env                          # secrets — never commit
├── .env.example                  # safe template to commit
├── watchlist.yaml                # user-defined tickers — edit freely
├── SPEC.md                       # this file — source of truth
├── deploy/                       # platform scheduling templates (implement after core logic)
│   ├── launchd/
│   │   └── com.personalinvestmentassistant.plist
│   └── systemd/
│       ├── pia-run@.service
│       ├── pia-pre-market.timer
│       ├── pia-midday.timer
│       └── pia-end-of-day.timer
├── logs/
│   ├── app.log                   # application logs (RotatingFileHandler)
│   ├── stdout.log                # service stdout (launchd / systemd)
│   ├── stderr.log                # service stderr (launchd / systemd)
│   └── scheduler.log             # skipped runs log
├── data/
│   ├── state.json                # Monitor output — Advisor + console read this
│   └── advisor/                  # Phase 3 — persisted conversation history
│       └── history.json
└── src/
    ├── run_graph.py              # manual CLI — `uv run pia-graph`
    ├── run_once.py               # scheduled CLI — `uv run pia-run`
    ├── run_advisor.py            # interactive advisor CLI (phase 2) — `uv run pia-advisor`
    ├── main.py                   # long-running daemon: schedule + Telegram (phase 2)
    ├── console.py                # rich terminal dashboard (separate process, read-only)
    ├── graph.py                  # LangGraph Monitor pipeline definition
    ├── state.py                  # AgentState TypedDict
    ├── state_persistence.py      # atomic state.json writer
    ├── config.py                 # pydantic-settings config
    ├── llm.py                    # get_llm() + get_advisor_llm() factories
    ├── nodes/
    │   ├── market_data.py        # fetch prices + compute indicators
    │   ├── news_analyst.py       # fetch + score news (batched, no reasoning)
    │   ├── supervisor.py         # graph entry: calendar gate + parallel fan-out
    │   ├── discovery.py          # suggest correlated instruments (no reasoning)
    │   ├── analyst.py            # rule-based signals + rationale polish (no reasoning)
    │   ├── notifier.py           # dispatch Telegram + email
    │   └── advisor.py            # on-demand reasoning over state.json (phase 2)
    ├── bot/
    │   └── telegram_handlers.py  # /ask, /brief, /status, /stop
    ├── web/                      # Phase 4 — browser UI (planned)
    │   ├── app.py                # local HTTP server — `uv run pia-web`
    │   ├── routes.py
    │   └── static/               # HTML/CSS/JS or lightweight SPA
    └── tools/
        ├── yfinance_tool.py
        ├── indicators.py
        ├── news_fetcher.py
        ├── quote_tool.py         # Phase 3 — on-demand live quotes for Advisor
        ├── fundamentals_tool.py  # Advisor only — trailing/forward P/E, PEG via yfinance
        ├── market_calendar.py    # pandas_market_calendars wrapper
        ├── telegram_client.py
        └── email_client.py
```

---

## Service Lifecycle — Scheduling

> **Implement after core logic is complete.** The LangGraph pipeline (`pia-graph`) is platform-independent. Deployment adds OS-native schedulers that invoke a one-shot entry point (`pia-run`) at the configured times.

### Shared behaviour (macOS + Linux)

- **Schedule:** 08:00, 13:00, 17:30 in `TIMEZONE` from `.env` (default `Europe/Rome`)
- **Entry command:** `uv run pia-run --run-type {pre_market|midday|end_of_day}`
- **Each run:** invoke graph → write `data/state.json` atomically → exit
- **No auto-respawn** on crash (equivalent to launchd `KeepAlive: false`)
- **Skip logging:** market-closed skips → `logs/scheduler.log`
- **Application logs:** `logs/app.log` (see `logging_config.py`)

### One-shot entry point (`pia-run`)

```bash
uv run pia-run --run-type pre_market
uv run pia-run --run-type midday
uv run pia-run --run-type end_of_day
```

Wraps Monitor `graph.ainvoke()` with the correct `run_type`, persists final state to `data/state.json`, and exits with a non-zero code only on fatal failure.

Manual development uses `uv run pia-graph` (same Monitor pipeline, interactive Rich output).

---

### macOS — launchd

Use a **launchd user agent** with calendar intervals — one plist per scheduled run, or one plist with multiple `StartCalendarInterval` entries. Each invocation runs `pia-run` as a one-shot job (not a long-running daemon).

#### Plist template (`deploy/launchd/com.personalinvestmentassistant.pre-market.plist`)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.personalinvestmentassistant.pre-market</string>

    <key>ProgramArguments</key>
    <array>
        <string>/ABS/PATH/TO/Personal-Investment-Assistant/.venv/bin/pia-run</string>
        <string>--run-type</string>
        <string>pre_market</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/ABS/PATH/TO/Personal-Investment-Assistant</string>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>/ABS/PATH/TO/Personal-Investment-Assistant/logs/stdout.log</string>

    <key>StandardErrorPath</key>
    <string>/ABS/PATH/TO/Personal-Investment-Assistant/logs/stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
        <key>TZ</key>
        <string>Europe/Rome</string>
    </dict>
</dict>
</plist>
```

Repeat for `midday` (13:00) and `end_of_day` (17:30), or maintain three separate plists.

#### Install (macOS)

```bash
cp deploy/launchd/*.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.personalinvestmentassistant.pre-market.plist
# repeat for each plist
```

#### Stop (macOS)

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.personalinvestmentassistant.pre-market.plist
```

Stop scheduled runs manually before using resource-intensive local apps (e.g. a DAW on macOS) — there is no automatic conflict detection.

---

### Linux — systemd user timers

Use **systemd user units**: one oneshot service plus one timer per scheduled run. Install to `~/.config/systemd/user/`.

#### Service unit (`deploy/systemd/pia-run@.service`)

Template unit — one invocation per run type:

```ini
[Unit]
Description=Personal Investment Assistant — pipeline run (%i)
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/ABS/PATH/TO/Personal-Investment-Assistant
EnvironmentFile=/ABS/PATH/TO/Personal-Investment-Assistant/.env
Environment=TZ=Europe/Rome
ExecStart=/ABS/PATH/TO/Personal-Investment-Assistant/.venv/bin/pia-run --run-type %i
StandardOutput=append:/ABS/PATH/TO/Personal-Investment-Assistant/logs/stdout.log
StandardError=append:/ABS/PATH/TO/Personal-Investment-Assistant/logs/stderr.log
```

Each timer triggers the service instance, e.g. `pia-run@pre_market.service`.

#### Timer unit example (`deploy/systemd/pia-pre-market.timer`)

```ini
[Unit]
Description=Personal Investment Assistant — pre-market run (08:00 CET)

[Timer]
OnCalendar=*-*-* 08:00:00
Persistent=true
Unit=pia-run@pre_market.service

[Install]
WantedBy=timers.target
```

Repeat for `pia-midday.timer` (13:00) and `pia-end-of-day.timer` (17:30).

#### Install (Linux)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pia-pre-market.timer pia-midday.timer pia-end-of-day.timer
loginctl enable-linger "$USER"   # optional: run timers when not logged in
```

#### Stop (Linux)

```bash
systemctl --user disable --now pia-pre-market.timer pia-midday.timer pia-end-of-day.timer
```

---

### Phase 2 — Advisor daemon (`main.py` / `pia-bot`)

The decision-assistant features require a **persistent process** with Telegram polling and optional in-process scheduling:

| Platform | Mechanism |
|---|---|
| macOS | launchd user agent with `KeepAlive: false`, started manually or at login |
| Linux | `systemd` user service (`pia-bot.service`), not a timer |

Timer-only deployment (phase 1 deploy) runs **Monitor mode only** — no `/ask`, `/brief`, or `/stop`. Stop scheduled runs via `launchctl bootout` or `systemctl --user disable`. Start the advisor daemon separately when you want interactive decision support.

The daemon can either:
- **Trigger Monitor runs** via `APScheduler` (replaces external timers), or
- **Coexist** with launchd/systemd timers — Advisor reads `state.json` written by `pia-run`

See [Advisor Mode](#advisor-mode-on-demand-reasoning) and [Telegram Bot Commands](#telegram-bot-commands).

---

## Advisor Mode (On-Demand Reasoning)

Advisor mode is the **decision-support layer**. It does not replace Monitor runs — it **interprets** their output when the user asks.

### Inputs

| Source | Used for |
|---|---|
| `data/state.json` | Latest signals, news scores, suggestions, watchlist note, errors |
| `watchlist.yaml` | Ticker names, alert thresholds, user's monitored universe |
| User message | Question, scenario, or `/brief` trigger |
| Optional conversation history | Multi-turn `/ask` follow-ups (in-memory per session, phase 2) |

If `state.json` is missing or stale (> 2 hours), Advisor warns the user and suggests running `pia-graph` or waiting for the next scheduled run.

### Use cases

**1. Macro picture (`/brief`)**

After a Monitor run, produce a watchlist-specific narrative:

- What macro themes matter **for your tickers** this week (rates, sector rotation, geopolitics)
- Top 2–3 conflicts or alignments across the watchlist
- What to watch before the next run — not generic market news

**2. Conflict resolution (`/ask`)**

When technical signals and news disagree:

```
User: AAPL is BUY on RSI but news sentiment is -0.6. How should I read that?
Advisor: [reasoning] → balanced interpretation with explicit assumptions
```

Facts (RSI value, sentiment score, signal label) come from `state.json`; reasoning weighs them.

**3. Scenario analysis (`/ask`)**

Open-ended what-if questions grounded in the watchlist:

```
User: If rates stay high for 6 months, what might that mean for MU vs SPY in my list?
Advisor: [reasoning] → scenario branches, risks, what would change the view
```

**4. Interactive follow-up (`/ask`)**

Multi-turn conversation referencing prior Monitor state and earlier messages in the session. Deep discovery questions ("why SMH over XLK for my book?") belong here, not in scheduled Discovery.

### Advisor node (`nodes/advisor.py`)

```python
async def advisor_respond(
    *,
    question: str,
    state: dict,           # loaded from state.json
    watchlist: list[WatchlistEntry],
    history: list[dict],   # optional conversation turns
    mode: str = "ask",     # "ask" | "brief"
) -> str:
    """Single entry point for all Advisor LLM calls — uses get_advisor_llm()."""
```

Prompt structure:

1. System: advisory-only, no portfolio access, state assumptions explicitly, disclaimer
2. Context block: serialized signals, news summary, watchlist note, suggestions from `state.json`
3. Watchlist block: tickers + names from `watchlist.yaml`
4. On-demand blocks (fetched per request, not from Monitor): indicator scan, ad-hoc analysis, live quotes, **valuation metrics**, fresh headlines
5. User question (or brief template for `/brief`)
6. Instruction: reason step-by-step internally; respond with clear prose, trade-offs, and stated assumptions

### Output rules

- Always append: `⚠️ Not financial advice. Always do your own research.`
- Never issue direct buy/sell orders — frame as "consider", "watch for", "conflict to resolve"
- Cite signal data from state (e.g. "RSI 28, sentiment -0.6") — do not invent numbers
- If data is insufficient, say so — do not hallucinate prices or headlines
- Reasoning tokens stay internal (Ollama `reasoning=True`); user sees final prose only

### Entry points

| Entry | Command | Phase |
|---|---|---|
| Telegram `/brief` | One-shot daily narrative after latest run | 2 |
| Telegram `/ask <question>` | Free-form reasoning query | 2 |
| CLI `uv run pia-advisor` | REPL reading `state.json` | 2 |
| Daemon `uv run pia-bot` | Hosts Telegram handlers + optional scheduler | 2 |

### Performance expectations

Advisor calls are **slow by design** (reasoning ON, longer `num_predict`). Typical latency: 30s–3min depending on model and GPU. The user triggers them explicitly and accepts the wait. Monitor runs remain fast (< 2 min target with `reasoning=False` and batched news).

### Phase 2 enhancements (implemented)

The following Advisor capabilities shipped with Phase 2 and are **not** deferred to Phase 3:

- **Fresh headlines** — Google News RSS fetched on demand for tickers mentioned in `/ask` or `/brief` (7-day window)
- **Useful links** — headline URLs plus Yahoo Finance quote and Google News search links appended to every Advisor reply
- **Session disclaimer** — financial-advice disclaimer shown once per CLI session or Telegram `/start`, not on every message

Phase 3 adds **persisted** memory, **proactive** brief delivery, **live quotes**, **valuation metrics**, **ad-hoc/scanned** market analysis, and **production deployment scripts** for the Advisor daemon.

### Phase 3+ — valuation metrics (Advisor only)

- **`src/tools/fundamentals_tool.py`** — on-demand yfinance fetch of trailing P/E, forward P/E, and PEG
- Wired into `advisor_respond()` as a **Valuation metrics** prompt block (parallel to live quotes)
- Fetched for `/brief` (full watchlist) and `/ask` (tickers targeted for the question)
- **Not** used by the Monitor pipeline — fundamentals change slowly and are irrelevant to scheduled signal alerts
- Config: `ADVISOR_FETCH_FUNDAMENTALS=true` (default true)
- PEG is included when yfinance returns it; often missing for ETFs and some symbols — LLM must not invent values

---

## Telegram Bot Commands

> **Phase 2** — requires long-running `main.py` / `pia-bot` daemon. Not available in timer-only deployment.

All commands verify the sender matches `TELEGRAM_CHAT_ID` — unauthorized requests are silently ignored.

| Command | Action |
|---|---|
| `/brief` | Advisor mode — macro picture + conflicts + what to watch (uses latest `state.json`) |
| `/ask <question>` | Advisor mode — free-form reasoning (scenarios, conflicts, follow-ups) |
| `/status` | Reports scheduler state, last Monitor run, next scheduled runs |
| `/stop` | Graceful shutdown — stops scheduler, Telegram polling, and exits the process |

Plain-text messages (no command) may be treated as `/ask` shorthand in a future iteration — v2 starts with explicit `/ask` only.

### `/stop` implementation

Shutting down must stop all async work and exit cleanly (`KeepAlive: false` — launchd will not restart):

```python
async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != settings.TELEGRAM_CHAT_ID:
        return  # silently ignore unauthorized
    await update.message.reply_text("🛑 Shutting down Personal Investment Assistant...")
    scheduler.shutdown(wait=False)
    await context.application.stop()
    await context.application.shutdown()
```

### `/status` response format

```
🤖 Personal Investment Assistant — Running

⏱ Next runs (CET):
  • Pre-market:  08:00
  • Midday:      13:00
  • End of day:  17:30

🧠 Model: qwen3:8b
📋 Watchlist: 5 tickers
🕐 Last run: 13:00 — 4 signals sent
```

### `/status` implementation

```python
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != settings.TELEGRAM_CHAT_ID:
        return
    jobs = scheduler.get_jobs()
    next_runs = "\n".join(
        f"  • {job.name}: {job.next_run_time.strftime('%H:%M')}"
        for job in jobs
    )
    msg = (
        f"🤖 Personal Investment Assistant — Running\n\n"
        f"⏱ Next runs (CET):\n{next_runs}\n\n"
        f"🧠 Model: {settings.OLLAMA_MODEL}\n"
        f"📋 Watchlist: {len(settings.watchlist)} tickers\n"
        f"🕐 Last run: {context.bot_data.get('last_run', 'N/A')}"
    )
    await update.message.reply_text(msg)
```

### `/brief` response format

```
📋 Daily brief — your watchlist (pre_market run, 08:02)

Macro: Rate expectations and semis strength dominate your list this week.
MU and AAPL both lean bullish technically, but overnight headlines skew cautious.

Conflicts:
  • AAPL — BUY (HIGH) vs news sentiment -0.6: oversold bounce vs negative headlines
  • SPY — HOLD with flat news: no clear edge

Watch today: US CPI release; monitor MU volume if memory names re-rate.

⚠️ Not financial advice. Always do your own research.
```

### `/ask` example

```
User: /ask If QQQ keeps outperforming SPY, should I shift attention within my ETFs?

Advisor: [reasoning internally]
Given your watchlist note (QQQ +8% YTD vs SPY) and current HOLD signals on both...
[balanced analysis with assumptions stated]

⚠️ Not financial advice. Always do your own research.
```

---

## Discovery Node — Correlated Instruments

`nodes/discovery.py` runs in **Monitor mode only** (reasoning OFF). It produces quick, validated ticker suggestions for notifications — not deep comparative analysis.

Deep questions ("why this ETF over that one for my situation?") belong in **Advisor mode** (`/ask`).

### How it works

The LLM receives the watchlist and returns structured JSON — sector peers, thematic ETFs, macro correlators, geographic pairs:

- **Sector peers** — if AAPL is in the watchlist, suggest MSFT, GOOGL, or SMH (semiconductor ETF)
- **Thematic ETFs** — if individual tech stocks are monitored, suggest QQQ or XLK
- **Macro correlators** — if SPY is watched, suggest TLT (bonds) or GLD (gold) as hedging context
- **Geographic pairs** — if US stocks are monitored, suggest equivalent European or EM exposure

### Output per run

```python
{
  "ticker": "SMH",
  "name": "VanEck Semiconductor ETF",
  "reason": "High overlap with AAPL and MSFT — semiconductor exposure relevant to your watchlist",
  "type": "SUGGESTION",          # always SUGGESTION, never treated as watchlist
  "confidence": "HIGH" | "MEDIUM"
}
```

### Rules

- Suggestions are **always labelled** as such in notifications — never mixed with watchlist signals
- Maximum 3 suggestions per run to avoid noise
- A suggestion that appears in the watchlist is silently skipped
- Low confidence suggestions are suppressed
- **Validate every suggested ticker** via yfinance before inclusion — drop invalid or unresolvable symbols and log a warning
- The user adds a suggestion to `watchlist.yaml` manually if they want it monitored — the agent never modifies the watchlist

### Notification format (suggestions section)

```
💡 Related instruments to watch:
  SMH — VanEck Semiconductor ETF — High overlap with your AAPL/MSFT watchlist
  TLT — iShares 20Y Treasury Bond ETF — Inverse correlation to SPY — useful hedge context
```

---

## Terminal Console (`src/console.py`)

A live read-only dashboard rendered with `rich` in a separate terminal. It reads `data/state.json` written by the scheduler after each run — no coupling to the service process.

### Launch

```bash
uv run python src/console.py
```

`q` quits the console only — the service keeps running under launchd.

### Layout

```
┌─ Personal Investment Assistant ──────────────────────────────┐
│ Status: Running │ Model: qwen3:8b │ 13:00 in 1h23m │
├──────────────────────────────────────────────────────────────┤
│ Watchlist signals — last run 08:00                           │
│                                                              │
│  🟢 AAPL   BUY   HIGH   RSI oversold (28), MACD cross        │
│  🔴 MSFT   SELL  MED    RSI overbought (74)                  │
│  ⚪ SPY    HOLD  —      No confirming signals                 │
│  ⚪ QQQ    HOLD  —      No confirming signals                 │
│  🟡 VWCE   WATCH LOW    EMA weakening                        │
├──────────────────────────────────────────────────────────────┤
│ 💡 Suggested                                                 │
│  SMH  — Semiconductor ETF — high overlap with AAPL/MSFT      │
│  TLT  — 20Y Treasury — inverse SPY correlation               │
├──────────────────────────────────────────────────────────────┤
│ Errors: none                         Refresh: 10s  [q] quit  │
└──────────────────────────────────────────────────────────────┘
```

### Design rules

- Refresh every 10 seconds via `rich.Live`
- Read-only — console never writes to `state.json` or controls the scheduler
- If `state.json` is missing or stale (> 2 hours old), display a warning banner
- `q` exits cleanly without affecting the service
- No colour assumptions — use `rich` style tokens, not hardcoded ANSI codes

### Shared state file (`data/state.json`)

Written by Monitor runs after every pipeline execution. **Console and Advisor read this file** — it is the shared bridge between fast scheduled monitoring and on-demand decision support.

**Write atomically:** write to `data/state.json.tmp`, then `os.replace()` to `data/state.json` so readers never see a partial file.

```json
{
  "last_run": "2026-06-03T08:00:00",
  "run_type": "pre_market",
  "next_runs": {
    "pre_market": "08:00",
    "midday": "13:00",
    "end_of_day": "17:30"
  },
  "model": "qwen3:8b",
  "watchlist_count": 5,
  "signals": [...],
  "suggestions": [...],
  "watchlist_note": "QQQ has outperformed SPY by 8% YTD among your watchlist.",
  "errors": []
}
```

---

## Watchlist (`watchlist.yaml`)

```yaml
stocks:
  - ticker: AAPL
    name: Apple Inc.
    alerts:
      rsi_oversold: 30
      rsi_overbought: 70
  - ticker: MSFT
    name: Microsoft Corp.
    alerts:
      rsi_oversold: 30
      rsi_overbought: 70

etfs:
  - ticker: SPY
    name: S&P 500 ETF
  - ticker: QQQ
    name: Nasdaq-100 ETF
  - ticker: VWCE.DE
    name: Vanguard All-World (Euronext)
```

Edit this file freely — no code changes needed to add/remove tickers.

Per-ticker `alerts.rsi_oversold` / `rsi_overbought` override the global defaults (30 / 70) when present.

---

## Technical Indicators

| Indicator | Parameters | Signal logic |
|---|---|---|
| RSI | period=14 | Below oversold threshold → bullish / above overbought → bearish |
| MACD | fast=12, slow=26, signal=9 | Cross above signal → bullish / cross below → bearish |
| EMA | 20 and 50 periods | Price above EMA20 > EMA50 → uptrend |
| Bollinger Bands | period=20, std=2 | Price at lower band → potential bounce |

**RSI thresholds:** per-ticker values from `watchlist.yaml` `alerts`; default oversold = 30, overbought = 70.

- Minimum 30 daily candles required — skip ticker if insufficient data
- At least 2 confirming indicator signals required before issuing BUY or SELL
- Use **daily OHLCV only** — no intraday data for trend signals (see Schedule for how midday runs differ)

---

## News Analysis

- **Sources**: configurable RSS feeds in `.env` plus a watchlist-specific Google News feed built at runtime
- **Fetch**: `httpx` async GET; validate each feed URL at startup and log failures
- **Sentiment**: scored -1.0 to +1.0 via local Ollama — **one batched call** for all tickers, `reasoning=False`
- **Relevance filter**: only news mentioning the ticker or company name
- **Time window**: last 24 hours only

RSS feeds break often — treat feed errors as non-fatal; append to `state["errors"]` and continue with technical signals only.

---

## Signal Generation

### Technical score

Each indicator contributes **+0.25** toward a directional score when it confirms bullish or bearish (max 1.0 from four indicators):

```
technical_score = min(1.0, confirming_indicators * 0.25)
```

Map `news_sentiment` from [-1.0, +1.0] to [0.0, 1.0]: `(news_sentiment + 1) / 2`.

Combined strength:

```
signal_strength = (technical_score * 0.7) + (normalized_news * 0.3)
```

### Signal assignment

| Condition | Signal |
|---|---|
| ≥ 2 bullish confirmations and strength ≥ 0.5 | BUY |
| ≥ 2 bearish confirmations and strength ≥ 0.5 | SELL |
| Exactly 1 confirmation | WATCH |
| Otherwise | HOLD |

### Confidence

| Strength | Confidence |
|---|---|
| ≥ 0.75 | HIGH |
| ≥ 0.55 | MEDIUM |
| < 0.55 | LOW |

```python
{
  "ticker": "AAPL",
  "signal": "BUY" | "SELL" | "HOLD" | "WATCH",
  "strength": 0.0–1.0,
  "rationale": "RSI oversold (28), MACD bullish cross, neutral news",
  "confidence": "HIGH" | "MEDIUM" | "LOW"
}
```

- `confidence: LOW` signals are computed but not sent in notifications (when `SKIP_LOW_CONFIDENCE=true`)
- `WATCH` signals with MEDIUM or HIGH confidence are included in notifications; LOW WATCH is suppressed

### Watchlist comparison note

Optional one-liner when the watchlist has ≥ 2 symbols with valid YTD data — e.g. relative performance among **monitored tickers only**. No holdings, weights, or rebalancing advice. Computed in `analyst.py`; LLM may rephrase for the notification.

---

## Notification Format

```
📊 Market Update — 17:30 CET

🟢 AAPL — BUY (HIGH confidence)
RSI: 28 (oversold) | MACD: bullish cross | News: Neutral

🔴 MSFT — SELL (MEDIUM confidence)
RSI: 74 (overbought) | EMA trend: weakening | News: Negative (-0.6)

📋 Watchlist note:
Among your monitored ETFs, QQQ has outperformed SPY by 8% YTD.

💡 Related instruments to watch:
  SMH — VanEck Semiconductor ETF — High overlap with your AAPL/MSFT watchlist
  TLT — iShares 20Y Treasury Bond ETF — Inverse correlation to SPY — useful hedge context

⚠️ Not financial advice. Always do your own research.
```

- Disclaimer always appended
- Send when there is at least one notifiable signal (BUY/SELL, or WATCH with MEDIUM/HIGH confidence), **or** validated discovery suggestions, **or** a watchlist note
- Skip notification only when all signals are HOLD/LOW, no suggestions, and no watchlist note
- Max 10 tickers per message; truncate with a note if watchlist is larger
- Telegram bot commands: `/brief`, `/ask`, `/status`, `/stop` (phase 2 daemon — see Advisor Mode)
- Email subject: `[PIA] Market Update — {date}` (optional — see `EMAIL_ENABLED`)

---

## Schedule

All times use `TIMEZONE` from `.env` (default `Europe/Rome` / CET). Scheduler uses `AsyncIOScheduler`.

| Run | Time (CET) | Purpose |
|---|---|---|
| Pre-market | 08:00 | Overnight news digest + full signal pass on latest daily data |
| Midday | 13:00 | News refresh and sentiment update; re-run Analyst on **unchanged daily indicators** |
| End of day | 17:30 | Full daily summary after US cash session |

**Midday caveat:** technical indicators use daily OHLCV only — RSI/MACD/EMA do not change intraday. The midday Monitor run adds value via fresh news and updated rationale polish, not new candle-based signals. Use Advisor `/ask` for intraday interpretation if needed.

### Market calendar (v1)

- Map each watchlist ticker to an exchange (US symbols → NYSE, `.DE` suffix → XETRA, etc.)
- **Skip the run** when every mapped exchange is closed for that calendar day (weekends + exchange holidays)
- Log skipped runs to `logs/scheduler.log` with reason and date

---

## Configuration (`.env`)

```bash
# LLM — edit OLLAMA_MODEL to swap without code changes
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b

# Monitor pipeline — fast, reasoning OFF
OLLAMA_NUM_CTX=8192
OLLAMA_NUM_PREDICT=512

# Advisor mode — reasoning ON (phase 2)
OLLAMA_ADVISOR_NUM_CTX=16384
OLLAMA_ADVISOR_NUM_PREDICT=4096

# Telegram
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Email
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_ADDRESS=your@email.com
EMAIL_PASSWORD=your_app_password
EMAIL_RECIPIENT=your@email.com

# News — watchlist-specific Google News feed is added automatically at runtime
RSS_FEEDS=https://feeds.content.dowjones.io/public/rss/mw_topstories,https://feeds.bbci.co.uk/news/business/rss.xml,https://news.google.com/rss/search?q=stock+market&hl=en-US&gl=US&ceid=US:en

# Behaviour
TIMEZONE=Europe/Rome
SKIP_LOW_CONFIDENCE=true
MAX_TICKERS_PER_NOTIFICATION=10
MAX_NEWS_HEADLINES_PER_TICKER=5
MAX_NEWS_HEADLINES_TOTAL=20
EMAIL_ENABLED=false
LOG_LEVEL=INFO
LOG_TO_CONSOLE=false
ADVISOR_STALE_STATE_HOURS=2
ADVISOR_NEWS_WINDOW_HOURS=168
ADVISOR_NEWS_HEADLINES_PER_TICKER=8

# Phase 3 — Advisor production
ADVISOR_HISTORY_MAX_TURNS=20
ADVISOR_FETCH_QUOTES=true
ADVISOR_FETCH_FUNDAMENTALS=true
PROACTIVE_BRIEF_ENABLED=false
PROACTIVE_BRIEF_VIA=telegram
PROACTIVE_BRIEF_SKIP_IF_NOTIFY=false

# Phase 4 — web UI
PIA_WEB_HOST=127.0.0.1
PIA_WEB_PORT=8765
PIA_WEB_TOKEN=
```

---

## Error Handling

- Nodes never raise — catch internally and append to `state["errors"]`
- Graph continues even if a node fails (degraded output beats silence)
- If all nodes fail → send a minimal error alert via Telegram
- Notifier retries once after 60 seconds on failure

---

## External Dependencies & Resilience

| Dependency | Risk | Mitigation |
|---|---|---|
| **yfinance** | Unofficial API; rate limits and breakage | Per-ticker retry (max 2); cache last-good OHLCV in memory for the run; log and skip failed tickers |
| **RSS feeds** | URLs change or return empty | Validate at startup; configurable `RSS_FEEDS`; continue without news on failure |
| **Ollama (Monitor)** | Latency under load | `reasoning=False`; batch news in one call; `num_ctx=8192`; cap headlines |
| **Ollama (Advisor)** | Slow responses expected | User-triggered only; `reasoning=True`; show "thinking…" in Telegram |
| **Discovery LLM** | Invalid ticker hallucination | Validate every suggestion via yfinance; deep analysis → Advisor `/ask` |

---

## Testing

**Phase 1 — Monitor pipeline (manual smoke checklist)**

- [ ] `uv run pia-graph` completes on **macOS** with signals in output
- [ ] `uv run pia-graph` completes on **Linux** with signals in output (same `.env` + watchlist)
- [ ] Ollama reachable — `ollama ps` shows model loaded; GPU backend as expected for host
- [ ] Monitor run completes in reasonable time with `reasoning=False` (< 2 min for ~8 tickers)
- [ ] Fetch one watchlist ticker via `yfinance_tool` — OHLCV + indicators present
- [ ] `market_calendar` returns correct open/closed for today
- [ ] Full graph run produces `data/state.json` with signals
- [ ] Telegram bot sends a test notification to `TELEGRAM_CHAT_ID` (when configured)
- [ ] Console displays `state.json` without error
- [ ] launchd timers or systemd timers fire `pia-run` at expected times (post-deploy)

**Phase 2 — Advisor mode**

- [ ] `/brief` returns watchlist-specific narrative using latest `state.json`
- [ ] `/ask` resolves a technical vs news conflict using real signal data from state
- [ ] `/ask` scenario question states assumptions explicitly; no invented prices
- [ ] Advisor warns when `state.json` is missing or stale (> `ADVISOR_STALE_STATE_HOURS`)
- [ ] `/status` and `/stop` respond from authorized chat only
- [ ] `uv run pia-advisor` REPL works without Telegram
- [ ] Monitor pipeline still uses `get_llm()` (reasoning OFF) after Advisor is added

**Phase 3 — Advisor production & live data**

- [x] Conversation history survives `pia-advisor` and `pia-bot` restarts
- [x] Pre-market run triggers proactive `/brief` when `PROACTIVE_BRIEF_ENABLED=true` (hook in `run_once.py`; live dispatch requires Telegram/email configured)
- [x] Advisor `/ask` includes live quote snapshot for mentioned tickers (price, change %, as-of)
- [x] Advisor `/ask` and `/brief` include valuation metrics when enabled (trailing P/E, forward P/E, PEG)
- [ ] `pia-bot` installed and running via launchd (macOS) or systemd (Linux) — install scripts ready; run `./deploy/install-pia-bot-macos.sh` when validated
- [x] Proactive brief does not duplicate the standard Monitor notification when `PROACTIVE_BRIEF_SKIP_IF_NOTIFY=true`
- [x] Ad-hoc ticker analysis for symbols not on the watchlist (`ADVISOR_ADHOC_ANALYSIS`)
- [x] Indicator scan for comparative questions (`ADVISOR_SCAN_*`, `data/advisor_scan_universe.yaml`)

**Phase 4 — Web application**

- [ ] `uv run pia-web` serves UI on configured localhost port
- [ ] Dashboard page mirrors `pia-console` data from `state.json`
- [ ] Advisor chat page supports `/brief`-equivalent and free-form questions with streaming or progress indicator
- [ ] Web app reuses `advisor_respond()` — no duplicated LLM logic
- [ ] Bind to localhost by default; optional auth token if exposed beyond loopback

---

## Phase 3 — Advisor Production & Live Data

Phase 3 turns the Phase 2 Advisor from a dev tool into a **daily driver**: memory that survives restarts, automatic morning briefs, fresher market data, and a properly installed daemon.

### 1. Persisted conversation memory

**Problem:** Phase 2 keeps history in memory only (`bot_data` / CLI session). Restarting `pia-bot` or `pia-advisor` loses context.

**Design:**

- Store history in `data/advisor/history.json` (atomic write, same pattern as `state.json`)
- Schema:

```json
{
  "updated_at": "2026-06-03T08:15:00+00:00",
  "telegram_chat_id": "123456789",
  "turns": [
    {"role": "user", "content": "Why did IBM rise?"},
    {"role": "assistant", "content": "…"}
  ]
}
```

- Cap at `ADVISOR_HISTORY_MAX_TURNS` (default 20 turns = 10 exchanges)
- Shared loader used by `pia-advisor` and `pia-bot` (`src/advisor_history.py`)
- `/clear` command (Telegram + CLI) resets history

### 2. Proactive `/brief` after pre-market run

**Problem:** User must manually run `/brief` each morning.

**Design:**

- After successful `pia-run --run-type pre_market`, optionally generate and send a daily brief
- Controlled by `.env`:

```bash
PROACTIVE_BRIEF_ENABLED=true
PROACTIVE_BRIEF_VIA=telegram   # telegram | email | both
```

- Flow: `run_once.py` → Monitor graph → persist `state.json` → if enabled, call `advisor_respond(mode="brief")` → dispatch via Telegram/email
- Send **only** when Telegram/email is configured and Monitor run was not skipped
- If Monitor notification already sent, proactive brief is a **separate message** (brief is narrative; Monitor alert is signal-focused). Set `PROACTIVE_BRIEF_SKIP_IF_NOTIFY=false` to always send both.

### 3. On-demand quote fetch

**Problem:** Advisor reasons over stale Monitor OHLCV; intraday `/ask` questions need current price.

**Design:**

- Add `src/tools/quote_tool.py` — lightweight yfinance fetch (latest price, day change %, volume, as-of timestamp)
- Advisor calls `fetch_quotes(tickers)` for mentioned watchlist symbols before building the prompt
- Inject a **Live quotes** block alongside existing **Fresh headlines** and **Useful links**
- Quotes are **facts from yfinance** — LLM must not invent prices when this block is present
- Config: `ADVISOR_FETCH_QUOTES=true` (default true in Phase 3)

### 4. On-demand valuation metrics (Advisor only)

**Problem:** Technical signals (RSI, MACD) do not answer “is this stock expensive?” — valuation ratios are a separate lens.

**Design:**

- Add `src/tools/fundamentals_tool.py` — yfinance fetch of trailing P/E, forward P/E, and PEG
- Advisor calls `fetch_fundamentals_batch(tickers)` before building the prompt (parallel with live quotes)
- Inject a **Valuation metrics** block — facts from yfinance; LLM must not invent P/E or PEG when absent
- Scope: `/brief` → full watchlist; `/ask` → tickers targeted for the question (mentioned symbols, ad-hoc tickers)
- **Monitor pipeline unchanged** — no fundamentals in `state.json` or scheduled notifications
- Config: `ADVISOR_FETCH_FUNDAMENTALS=true` (default true)

### 5. Install `pia-bot` service (Advisor daemon)

**Problem:** Phase 2 provides templates only; Advisor must run persistently for Telegram.

**Design:**

- **macOS:** install `deploy/launchd/com.personalinvestmentassistant.bot.plist` to `~/Library/LaunchAgents/`, replace `/ABS/PATH/…`, then:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.personalinvestmentassistant.bot.plist
```

- **Linux:** install `deploy/systemd/pia-bot.service` to `~/.config/systemd/user/`, then:

```bash
systemctl --user enable --now pia-bot.service
```

- Logs: `logs/bot-stdout.log`, `logs/bot-stderr.log`
- Install **after** Phase 3 features are validated locally via `uv run pia-bot`
- Monitor scheduled runs remain separate (`pia-run` timers) — `pia-bot` does not replace them

### Phase 3 build steps

24. `src/advisor_history.py` — load/save/clear persisted turns
25. Wire history into `run_advisor.py` and `bot/telegram_handlers.py`; add `/clear`
26. `src/tools/quote_tool.py` — on-demand quote fetch; wire into `advisor.py`
27. Proactive brief hook in `run_once.py` + config flags
28. `src/tools/fundamentals_tool.py` — on-demand P/E and PEG; Advisor prompt block only
29. Install and document `pia-bot` launchd/systemd service (final deploy step for Advisor)
30. Manual smoke tests — Phase 3 checklist

---

## Phase 4 — Web Application (Browser UI)

Phase 4 adds a **local web front-end** so Monitor state and Advisor chat are usable in a browser — same machine as Ollama, no cloud dependency.

### Goals

- View last Monitor run (signals, suggestions, watchlist note) in a browser dashboard
- Chat with the Advisor (brief + free-form questions) without Telegram or terminal REPL
- Reuse all existing Python logic — the web layer is a thin HTTP API over `state.json`, `advisor_respond()`, and `load_watchlist()`

### Non-goals (Phase 4)

- No public internet exposure by default
- No user accounts or multi-tenancy
- No portfolio import or trade execution
- No replacement of Ollama — browser talks to local API only

### Architecture

```
Browser  ←HTTP→  pia-web (FastAPI or Starlette)
                    ├── GET  /api/state        → load_state()
                    ├── POST /api/advisor/ask  → advisor_respond()
                    ├── POST /api/advisor/brief
                    └── GET  /                 → static SPA or server-rendered pages
```

- **Default bind:** `127.0.0.1:8765` (`PIA_WEB_HOST`, `PIA_WEB_PORT` in `.env`)
- **Auth (optional):** `PIA_WEB_TOKEN` header check when not localhost-only
- **Long requests:** return 202 + poll, or SSE stream for Advisor progress ("Fetching headlines…", "Thinking…")
- **CORS:** disabled except same-origin

### UI pages (minimum viable)

| Page | Content |
|---|---|
| **Dashboard** | Equivalent to `pia-console` — signals table, suggestions, watchlist note, stale banner |
| **Advisor** | Chat thread with brief button, message input, useful links rendered as clickable anchors |
| **About** | Model name, last run time, disclaimer (once per session in UI) |

### Tech choices

- **Backend:** FastAPI + uvicorn (add to `pyproject.toml`)
- **Frontend:** lightweight — server-rendered Jinja2 + HTMX, or small static SPA (no heavy build chain required for v1)
- **Entry point:** `uv run pia-web` → `src/web/app.py`

### Deployment

- Run manually during development
- Optional: launchd/systemd user service `pia-web.service` (separate from `pia-bot` and `pia-run`)
- Can run alongside `pia-bot` — web Advisor and Telegram Advisor share `advisor_history.json` if same session id is used (future refinement)

### Phase 4 build steps

30. `src/web/app.py` + routes — state and advisor API
31. Dashboard page (read `state.json`)
32. Advisor chat page (POST ask/brief, display useful links)
33. `pia-web` entry in `pyproject.toml`; config vars in `.env.example`
34. Optional `deploy/` service unit for `pia-web`
35. Manual smoke tests — Phase 4 checklist

---

## Coding Conventions

- All async I/O uses `asyncio` — no `threading`
- No `print()` in production — use stdlib `logging`
- No `requests` for async I/O — use `httpx` or `aiohttp`
- `yfinance` calls wrapped in `asyncio.to_thread()` (blocking library)
- Type hints on all function signatures
- Docstrings on all node functions and public tools
- Never instantiate `ChatOllama` outside `src/llm.py`
- Use `get_llm()` in Monitor nodes; use `get_advisor_llm()` only in `advisor.py`
- Never enable `reasoning=True` in Monitor pipeline nodes
- Never hardcode ticker symbols — always read from `watchlist.yaml`
- Never hardcode secrets — always read from `.env` via `pydantic-settings`

---

## Build Order

**Phase 1 — Monitor pipeline** ✅

1. `state.py` + `config.py` + `watchlist.yaml` loader
2. `llm.py` — `get_llm()` with `reasoning=False`
3. `tools/yfinance_tool.py` + `tools/indicators.py`
4. `tools/market_calendar.py`
5. `nodes/market_data.py`
6. `tools/telegram_client.py` + `tools/email_client.py`
7. `tools/news_fetcher.py` + `nodes/news_analyst.py` (single batched LLM call)
8. `nodes/discovery.py`
9. `nodes/analyst.py` — rule-based signals + rationale polish (notifiable only)
10. `nodes/notifier.py`
11. `nodes/supervisor.py` + `graph.py`
12. `run_graph.py` + `run_once.py` + `state_persistence.py`
13. Manual smoke tests — Monitor checklist

**Deployment — timer-only Monitor runs** ✅ (templates ready; install when project is complete)

14. `deploy/launchd/` — macOS calendar plists for three daily runs
15. `deploy/systemd/` — Linux user timers + oneshot service units
16. `src/console.py` — rich terminal dashboard

**Phase 2 — Advisor mode (decision support)** ✅

17. `llm.py` — add `get_advisor_llm()` with `reasoning=True`
18. `nodes/advisor.py` — `/brief` and `/ask` over `state.json` (+ fresh RSS, useful links)
19. `run_advisor.py` — interactive CLI REPL (`pia-advisor`)
20. `bot/telegram_handlers.py` — `/brief`, `/ask`, `/status`, `/stop`
21. `main.py` — long-running daemon (`pia-bot`) with Telegram polling
22. Deploy templates for `pia-bot` (launchd + systemd) — install deferred to Phase 3
23. Manual smoke tests — Advisor checklist

**Phase 3 — Advisor production & live data** ✅

24. `advisor_history.py` — persisted conversation across restarts ✅
25. `/clear` command; wire history into CLI and Telegram ✅
26. `quote_tool.py` — on-demand live quotes in Advisor prompts ✅
27. Proactive `/brief` after pre-market run (`PROACTIVE_BRIEF_*`) ✅
28. `advisor_on_demand.py`, `advisor_scan.py` — ad-hoc tickers + indicator scans ✅
29. `fundamentals_tool.py` — on-demand trailing/forward P/E and PEG in Advisor prompts ✅
30. Install scripts `deploy/install-pia-bot-macos.sh` / `install-pia-bot-linux.sh` ✅ (service bootstrap deferred until operator runs script)
31. Manual smoke tests — Phase 3 checklist ✅ (2026-06-03; `pia-bot` launchd/systemd install still operator step)

**Phase 4 — Web application (browser UI)**

30. `src/web/` — FastAPI app + static UI (`pia-web`)
31. Dashboard page (Monitor state from `state.json`)
32. Advisor chat page (brief + ask, useful links)
33. Localhost binding, optional auth token, config in `.env`
34. Optional `pia-web` deploy service unit
35. Manual smoke tests — Phase 4 checklist

---

## Dependencies (`pyproject.toml`)

```toml
[project]
name = "personal-investment-assistant"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    "langgraph>=0.2",
    "langchain-core>=0.3",
    "langchain-ollama>=0.2",
    "yfinance>=0.2",
    "pandas-ta>=0.3",
    "pandas-market-calendars>=4.0",
    "feedparser>=6.0",
    "python-telegram-bot>=21.0",
    "apscheduler>=3.10",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "rich>=13.0",
    "httpx>=0.27",
]
```

---

## References

- [LangGraph docs](https://langchain-ai.github.io/langgraph/)
- [pandas-ta docs](https://github.com/twopirllc/pandas-ta)
- [pandas-market-calendars docs](https://github.com/rsheftel/pandas_market_calendars)
- [python-telegram-bot docs](https://python-telegram-bot.org/)
- [yfinance docs](https://pypi.org/project/yfinance/)
- [rich docs](https://rich.readthedocs.io/)
- [launchd plist manual](https://www.launchd.info/)
- [systemd.timer man page](https://www.freedesktop.org/software/systemd/man/systemd.timer.html)
