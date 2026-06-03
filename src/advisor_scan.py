"""Broad indicator scans for comparative Advisor questions."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from src.config import PROJECT_ROOT, WatchlistEntry, settings
from src.tools.indicators import compute_indicators
from src.tools.yfinance_tool import fetch_ohlcv

logger = logging.getLogger(__name__)

DEFAULT_SCAN_UNIVERSE_PATH = PROJECT_ROOT / "data" / "advisor_scan_universe.yaml"

_COMPARATIVE_HINTS = re.compile(
    r"\b("
    r"highest|lowest|higher|lower|greater|less|most|least|"
    r"compare|comparison|versus|rank|which|best|worst|top|bottom"
    r")\b",
    re.IGNORECASE,
)
_INDICATOR_HINTS = re.compile(
    r"\b(rsi|macd|ema|bollinger|indicator|overbought|oversold)\b",
    re.IGNORECASE,
)
_BROAD_SCOPE_HINTS = re.compile(
    r"\b(overall|entire|market.?wide|any ticker|all stocks|broad|whole market|globally)\b",
    re.IGNORECASE,
)
_WATCHLIST_SCOPE_HINTS = re.compile(
    r"\b(my watchlist|my stocks|watchlist|monitored|my portfolio)\b",
    re.IGNORECASE,
)
_HIGH_DIRECTION = re.compile(
    r"\b(highest|higher|greater|most|high(est)?|top|max|overbought)\b",
    re.IGNORECASE,
)
_LOW_DIRECTION = re.compile(
    r"\b(lowest|lower|less|least|low(est)?|bottom|min|oversold)\b",
    re.IGNORECASE,
)
_SECTOR_PATTERNS: dict[str, re.Pattern[str]] = {
    "tech": re.compile(r"\b(tech|technology|software|semiconductor|semis|chip)\b", re.IGNORECASE),
    "energy": re.compile(r"\b(energy|oil|gas|petroleum)\b", re.IGNORECASE),
    "finance": re.compile(r"\b(finance|financial|bank|banking)\b", re.IGNORECASE),
    "healthcare": re.compile(
        r"\b(healthcare|health care|pharma|pharmaceutical|biotech)\b",
        re.IGNORECASE,
    ),
}


@dataclass(frozen=True)
class IndicatorLeader:
    ticker: str
    value: float


@dataclass(frozen=True)
class IndicatorScanResult:
    metric: str
    metric_label: str
    direction: str
    leader: IndicatorLeader
    trailing: IndicatorLeader | None
    ranking: tuple[IndicatorLeader, ...]
    universe_label: str
    universe_size: int
    scanned: int
    errors: tuple[str, ...]

    def to_prompt_dict(self) -> dict:
        return {
            "metric": self.metric,
            "metric_label": self.metric_label,
            "direction": self.direction,
            "exact_leader": {
                "ticker": self.leader.ticker,
                "value": round(self.leader.value, 2),
            },
            "exact_trailing": (
                {
                    "ticker": self.trailing.ticker,
                    "value": round(self.trailing.value, 2),
                }
                if self.trailing
                else None
            ),
            "ranking": [
                {"ticker": row.ticker, "value": round(row.value, 2)} for row in self.ranking
            ],
            "universe_label": self.universe_label,
            "universe_size": self.universe_size,
            "scanned": self.scanned,
            "errors": list(self.errors),
            "note": (
                "Values are computed in Python from live yfinance daily OHLCV — "
                "use exact_leader as the definitive answer."
            ),
        }

    def exact_answer_block(self) -> str:
        direction_word = "Highest" if self.direction == "highest" else "Lowest"
        lines = [
            "📊 Indicator scan",
            f"Universe: {self.universe_label} ({self.universe_size} tickers, "
            f"{self.scanned} with data)",
            f"{direction_word} {self.metric_label}: "
            f"{self.leader.ticker} — {self.leader.value:.1f}",
        ]
        if self.trailing and self.trailing.ticker != self.leader.ticker:
            opposite = "Lowest" if self.direction == "highest" else "Highest"
            lines.append(
                f"{opposite} {self.metric_label}: "
                f"{self.trailing.ticker} — {self.trailing.value:.1f}"
            )
        if len(self.ranking) > 1:
            top = ", ".join(f"{row.ticker} {row.value:.1f}" for row in self.ranking[:5])
            lines.append(f"Top 5 by {self.metric_label}: {top}")
        if self.errors:
            lines.append(f"Fetch errors: {len(self.errors)} tickers skipped")
        lines.append(
            "Scope: reference universe in data/advisor_scan_universe.yaml "
            "(expand file to widen coverage; not every listed equity worldwide)."
        )
        return "\n".join(lines)


def is_indicator_scan_question(question: str) -> bool:
    if not question.strip() or not settings.ADVISOR_SCAN_ENABLED:
        return False
    return bool(_COMPARATIVE_HINTS.search(question) and _INDICATOR_HINTS.search(question))


def _scan_direction(question: str) -> str:
    if _LOW_DIRECTION.search(question) and not _HIGH_DIRECTION.search(question):
        return "lowest"
    return "highest"


def _scan_metric(question: str) -> tuple[str, str]:
    if re.search(r"\bmacd\b", question, re.IGNORECASE):
        return "macd_hist", "MACD histogram"
    if re.search(r"\bema\b", question, re.IGNORECASE):
        return "ema_spread_pct", "EMA 20/50 spread %"
    return "rsi_14", "RSI (14)"


@lru_cache
def _load_universe_document() -> dict:
    path = Path(settings.ADVISOR_SCAN_UNIVERSE_PATH)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        logger.warning("Scan universe file missing: %s", path)
        return {"tickers": [], "sectors": {}}
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    if not isinstance(document, dict):
        return {"tickers": [], "sectors": {}}
    return document


def resolve_scan_universe(question: str, watchlist: list[WatchlistEntry]) -> tuple[list[str], str]:
    document = _load_universe_document()
    all_tickers = {
        str(ticker).strip().upper()
        for ticker in document.get("tickers", [])
        if str(ticker).strip()
    }
    all_tickers.update(entry.ticker.upper() for entry in watchlist)

    if _WATCHLIST_SCOPE_HINTS.search(question):
        tickers = [entry.ticker.upper() for entry in watchlist]
        return _cap_tickers(tickers), "watchlist"

    if _BROAD_SCOPE_HINTS.search(question) or not _matched_sector(question, document):
        return _cap_tickers(sorted(all_tickers)), "reference universe (broad)"

    sector = _matched_sector(question, document)
    if sector:
        sector_tickers = {
            str(ticker).strip().upper()
            for ticker in document.get("sectors", {}).get(sector, [])
            if str(ticker).strip()
        }
        sector_tickers.update(entry.ticker.upper() for entry in watchlist)
        return _cap_tickers(sorted(sector_tickers)), f"{sector} sector subset"

    return _cap_tickers(sorted(all_tickers)), "reference universe (broad)"


def _matched_sector(question: str, document: dict) -> str | None:
    sectors = document.get("sectors", {})
    if not isinstance(sectors, dict):
        return None
    for name, pattern in _SECTOR_PATTERNS.items():
        if name in sectors and pattern.search(question):
            return name
    return None


def _cap_tickers(tickers: list[str]) -> list[str]:
    unique = list(dict.fromkeys(tickers))
    return unique[: settings.ADVISOR_SCAN_MAX_TICKERS]


def _metric_value(metric: str, frame) -> float | None:
    latest = frame.iloc[-1]
    if metric == "rsi_14":
        value = latest.get("rsi_14")
        return float(value) if value == value else None  # NaN check

    if metric == "macd_hist":
        for column in frame.columns:
            if column.startswith("MACDh_"):
                value = latest.get(column)
                return float(value) if value == value else None
        return None

    if metric == "ema_spread_pct":
        ema20 = latest.get("ema_20")
        ema50 = latest.get("ema_50")
        if ema20 != ema20 or ema50 != ema50 or ema50 == 0:
            return None
        return ((float(ema20) - float(ema50)) / float(ema50)) * 100.0

    return None


async def _scan_one_ticker(
    ticker: str,
    metric: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, float | None, str | None]:
    async with semaphore:
        try:
            frame = await fetch_ohlcv(ticker)
            if frame is None:
                return ticker, None, f"{ticker}: insufficient OHLCV"
            enriched = compute_indicators(frame)
            value = _metric_value(metric, enriched)
            if value is None:
                return ticker, None, f"{ticker}: {metric} unavailable"
            return ticker, value, None
        except Exception as exc:
            return ticker, None, f"{ticker}: scan failed ({exc})"


async def run_indicator_scan(
    question: str,
    watchlist: list[WatchlistEntry],
) -> IndicatorScanResult | None:
    if not is_indicator_scan_question(question):
        return None

    metric, metric_label = _scan_metric(question)
    direction = _scan_direction(question)
    tickers, universe_label = resolve_scan_universe(question, watchlist)
    if not tickers:
        return None

    logger.info(
        "Advisor indicator scan metric=%s direction=%s universe=%s tickers=%d",
        metric,
        direction,
        universe_label,
        len(tickers),
    )

    semaphore = asyncio.Semaphore(settings.ADVISOR_SCAN_CONCURRENCY)
    results = await asyncio.gather(
        *[_scan_one_ticker(ticker, metric, semaphore) for ticker in tickers]
    )

    rows: list[IndicatorLeader] = []
    errors: list[str] = []
    for ticker, value, error in results:
        if error:
            errors.append(error)
        if value is not None:
            rows.append(IndicatorLeader(ticker=ticker, value=value))

    if not rows:
        return None

    rows.sort(key=lambda row: row.value, reverse=(direction == "highest"))
    leader = rows[0]
    trailing = rows[-1] if len(rows) > 1 else None
    ranking = tuple(rows[:10])

    return IndicatorScanResult(
        metric=metric,
        metric_label=metric_label,
        direction=direction,
        leader=leader,
        trailing=trailing,
        ranking=ranking,
        universe_label=universe_label,
        universe_size=len(tickers),
        scanned=len(rows),
        errors=tuple(errors),
    )


def format_scan_block(scan: IndicatorScanResult | None) -> str:
    if scan is None:
        return "No indicator scan was run for this question."
    return json.dumps(scan.to_prompt_dict(), indent=2, ensure_ascii=False)


def scan_status_message(scan: IndicatorScanResult | None) -> str | None:
    if scan is None:
        return None
    return (
        f"scanning {scan.metric_label} across {scan.universe_size} tickers "
        f"({scan.universe_label})"
    )
