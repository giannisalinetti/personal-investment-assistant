# Personal Investment Assistant — Project Specification

## Overview

An autonomous **advisory-only** multi-agent application built with **LangGraph** that monitors a user-defined watchlist of stocks and ETFs, performs technical and news-driven analysis, and delivers suggestions via **Telegram** and **Email**.

The agent has **no access to the user's portfolio** — no holdings, balances, cost basis, or broker integration. It reasons only over the watchlist in `watchlist.yaml` and public market data. All output is informational; the user decides whether to act.

**LangGraph** is the orchestration layer by design: this project doubles as a practical way to learn graph-based agent workflows (parallel nodes, shared state, conditional edges) on a real scheduled pipeline.

---

## Goals

- Monitor a user-defined watchlist of stocks and ETFs
- Suggest additional correlated instruments not in the watchlist
- Compute technical indicators (RSI, MACD, moving averages)
- Fetch and interpret relevant financial news and sentiment
- Generate buy/sell/hold/watch signals and **watchlist comparison notes** (relative performance among monitored symbols)
- Deliver notifications via Telegram bot and/or email
- Run autonomously on a schedule without manual intervention
- Provide a live terminal console for local monitoring
- Provide a simple way to stop the service gracefully at any time

## Non-Goals

- No real-money trading execution (read/analyze only)
- No portfolio tracking, holdings import, or position sizing — advisory over watchlist only
- No backtesting engine (v1)
- No web UI or dashboard (v1)
- No external LLM API calls — fully local inference via Ollama

---

## Architecture

### Agent Graph (LangGraph)

```
[Scheduler / Entry Point]
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
               (rule-based signals + LLM rationale + watchlist note)
                           │
                           ▼
               [Notifier Node]
               (Telegram + Email dispatch)

[Console — src/console.py]
(separate process, reads shared state.json, read-only)
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

| Responsibility | Implementation |
|---|---|
| RSI, MACD, EMA, Bollinger signals | Rule-based (`indicators.py`) |
| Signal strength and BUY/SELL/HOLD/WATCH | Rule-based (`analyst.py`) |
| News sentiment (-1.0 to +1.0) | LLM (`news_analyst.py`) |
| Correlated instrument suggestions | LLM (`discovery.py`), validated against yfinance |
| Human-readable rationale in notifications | LLM (`analyst.py`) |
| Watchlist comparison note (YTD relative performance) | Computed from market data; LLM may polish wording |

Keep deterministic logic in code; use the LLM for language and unstructured reasoning only.

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
| Scheduling (v1 deploy) | launchd (macOS) / systemd timers (Linux) | One-shot scheduled runs — see Service Lifecycle |
| Scheduling (optional) | `APScheduler` in `main.py` | Long-running daemon + Telegram `/stop` `/status` — phase 2 |
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
uv run pia-graph                 # manual graph run (development)
uv run pia-run --run-type manual # scheduled entry point (to be implemented)
uv run python src/console.py     # console (separate terminal)
```

---

## LLM — Interchangeable Model

The model is configured via `.env` and never hardcoded. All nodes use `get_llm()` from `src/llm.py` — the only place where `ChatOllama` is instantiated.

```python
# src/llm.py
from langchain_ollama import ChatOllama
from src.config import settings

def get_llm(temperature: float = 0.1) -> ChatOllama:
    return ChatOllama(
        model=settings.OLLAMA_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=temperature,
    )
```

To swap models, edit `.env` only — no code changes:

```bash
OLLAMA_MODEL=qwen3:8b     # default — fast, low VRAM
# OLLAMA_MODEL=qwen3:14b  # better quality, ~10GB VRAM
# OLLAMA_MODEL=qwen3:32b  # best quality, ~22GB VRAM, overnight only
# OLLAMA_MODEL=qwen2.5:7b # stable fallback if Qwen3 issues
```

**Never instantiate `ChatOllama` outside `src/llm.py`.**

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
│   └── state.json                # shared state written after each run (console reads this)
└── src/
    ├── run_graph.py              # manual CLI — `uv run pia-graph`
    ├── run_once.py               # scheduled CLI — `uv run pia-run` (to be implemented)
    ├── main.py                   # optional long-running daemon + Telegram commands (phase 2)
    ├── console.py                # rich terminal dashboard (separate process, read-only)
    ├── graph.py                  # LangGraph graph definition
    ├── state.py                  # AgentState TypedDict
    ├── config.py                 # pydantic-settings config
    ├── llm.py                    # get_llm() factory
    ├── nodes/
    │   ├── market_data.py        # fetch prices + compute indicators
    │   ├── news_analyst.py       # fetch + score news
    │   ├── supervisor.py         # graph entry: calendar gate + parallel fan-out
    │   ├── discovery.py          # suggest correlated instruments (LLM + validation)
    │   ├── analyst.py            # rule-based signals + LLM rationale + watchlist note
    │   └── notifier.py           # dispatch Telegram + email
    └── tools/
        ├── yfinance_tool.py
        ├── indicators.py
        ├── news_fetcher.py
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

### One-shot entry point (`pia-run`) — to be implemented

```bash
uv run pia-run --run-type pre_market
uv run pia-run --run-type midday
uv run pia-run --run-type end_of_day
```

Wraps `graph.ainvoke()` with the correct `run_type`, persists final state to `data/state.json`, and exits with a non-zero code only on fatal failure.

Manual development uses `uv run pia-graph` (same pipeline, interactive Rich output).

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

### Phase 2 — optional long-running daemon (`main.py`)

Telegram `/stop` and `/status` require a **persistent process** with `APScheduler` and bot polling:

| Platform | Mechanism |
|---|---|
| macOS | launchd user agent with `KeepAlive: false`, started manually or at login |
| Linux | `systemd` user service (`pia-bot.service`), not a timer |

Timer-only deployment (v1) does **not** include `/stop` or `/status` — stop scheduled runs via `launchctl bootout` or `systemctl --user disable` instead.

---

## Telegram Bot Commands

> **Phase 2** — requires long-running `main.py` daemon. Not available in timer-only deployment (v1).

All commands verify the sender matches `TELEGRAM_CHAT_ID` — unauthorized requests are silently ignored.

| Command | Action |
|---|---|
| `/stop` | Graceful shutdown — stops scheduler, Telegram polling, and exits the process |
| `/status` | Reports current scheduler state and next scheduled runs |

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

---

## Discovery Node — Correlated Instruments

`nodes/discovery.py` runs alongside the market data and news nodes. It analyses the user's watchlist and suggests additional instruments that are meaningfully correlated from a market perspective — sector peers, ETFs with high overlap, or instruments with historically high correlation to watchlist tickers.

### How it works

The LLM is prompted with the current watchlist and asked to reason about market relationships:

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
  SMH  — VanEck Semiconductor ETF
         High overlap with your AAPL/MSFT watchlist
  TLT  — iShares 20Y Treasury Bond ETF
         Inverse correlation to SPY — useful hedge context
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

Written by the scheduler after every run. Console reads this file.

**Write atomically:** write to `data/state.json.tmp`, then `os.replace()` to `data/state.json` so the console never reads a partial file.

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
- **Sentiment**: scored -1.0 to +1.0 via local Ollama (batch headlines where possible to limit calls)
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
  SMH  — High overlap with your AAPL/MSFT watchlist
  TLT  — Inverse correlation to SPY — useful hedge context

⚠️ Not financial advice. Always do your own research.
```

- Disclaimer always appended
- Send when there is at least one notifiable signal (BUY/SELL, or WATCH with MEDIUM/HIGH confidence), **or** validated discovery suggestions, **or** a watchlist note
- Skip notification only when all signals are HOLD/LOW, no suggestions, and no watchlist note
- Max 10 tickers per message; truncate with a note if watchlist is larger
- Telegram bot commands: `/stop`, `/status` (see Service Lifecycle section)
- Email subject: `[PIA] Market Update — {date}` (optional — see `EMAIL_ENABLED`)

---

## Schedule

All times use `TIMEZONE` from `.env` (default `Europe/Rome` / CET). Scheduler uses `AsyncIOScheduler`.

| Run | Time (CET) | Purpose |
|---|---|---|
| Pre-market | 08:00 | Overnight news digest + full signal pass on latest daily data |
| Midday | 13:00 | News refresh and sentiment update; re-run Analyst on **unchanged daily indicators** |
| End of day | 17:30 | Full daily summary after US cash session |

**Midday caveat:** technical indicators use daily OHLCV only — RSI/MACD/EMA do not change intraday. The midday run adds value via fresh news and updated LLM rationale, not new candle-based signals.

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
EMAIL_ENABLED=false
LOG_LEVEL=INFO
LOG_TO_CONSOLE=false
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
| **Ollama** | Latency under load; platform-specific GPU | Batch news sentiment; cap discovery to 3 suggestions; use `qwen3:8b` for scheduled runs; verify GPU with `ollama ps` (Metal on macOS, CUDA/ROCm on Linux) |
| **Discovery LLM** | Invalid ticker hallucination | Validate every suggestion via yfinance before state/notifications |

---

## Testing (v1)

No automated test suite required for v1 — use a manual smoke checklist before enabling scheduled deployment:

- [ ] `uv run pia-graph` completes on **macOS** with signals in output
- [ ] `uv run pia-graph` completes on **Linux** with signals in output (same `.env` + watchlist)
- [ ] Ollama reachable — `ollama ps` shows model loaded; GPU backend as expected for host
- [ ] Fetch one watchlist ticker via `yfinance_tool` — OHLCV + indicators present
- [ ] `market_calendar` returns correct open/closed for today
- [ ] Full graph run produces `data/state.json` with signals
- [ ] Telegram bot sends a test message to `TELEGRAM_CHAT_ID` (when configured)
- [ ] `/status` and `/stop` respond from authorized chat only (phase 2 daemon only)
- [ ] Console displays `state.json` without error
- [ ] launchd timers or systemd timers fire `pia-run` at expected times (post-deploy)

---

## Coding Conventions

- All async I/O uses `asyncio` — no `threading`
- No `print()` in production — use stdlib `logging`
- No `requests` for async I/O — use `httpx` or `aiohttp`
- `yfinance` calls wrapped in `asyncio.to_thread()` (blocking library)
- Type hints on all function signatures
- Docstrings on all node functions and public tools
- Never instantiate `ChatOllama` outside `src/llm.py`
- Never hardcode ticker symbols — always read from `watchlist.yaml`
- Never hardcode secrets — always read from `.env` via `pydantic-settings`

---

## Build Order

Recommended path to a working v1 (Telegram before email; graph before deployment):

**Core logic (current focus)**

1. `state.py` + `config.py` + `watchlist.yaml` loader
2. `llm.py` — verify Ollama connectivity before proceeding
3. `tools/yfinance_tool.py` + `tools/indicators.py`
4. `tools/market_calendar.py` — verify holiday/weekend skipping
5. `nodes/market_data.py` — verify indicator output manually
6. `tools/telegram_client.py` — wire up early for fast feedback
7. `tools/news_fetcher.py` + `nodes/news_analyst.py`
8. `nodes/discovery.py` — correlated instrument suggestions + yfinance validation
9. `nodes/analyst.py` — rule-based signals + watchlist note
10. `nodes/notifier.py` — Telegram first; email when `EMAIL_ENABLED=true`
11. `nodes/supervisor.py` + `graph.py` — parallel fan-out and join
12. `run_graph.py` — manual CLI (`pia-graph`) for development
13. Manual smoke tests (see Testing section)

**Deployment (after core logic)**

14. `run_once.py` — scheduled CLI (`pia-run`) + atomic `state.json` writer
15. `deploy/launchd/` — macOS calendar plists for three daily runs
16. `deploy/systemd/` — Linux user timers + oneshot service units
17. `src/console.py` — rich terminal dashboard

**Optional phase 2**

18. `main.py` — long-running `AsyncIOScheduler` + Telegram commands (`/stop`, `/status`)
19. launchd agent or `systemd` user service for persistent bot process

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
