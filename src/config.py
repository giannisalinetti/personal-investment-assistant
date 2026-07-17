"""Application configuration and watchlist loading."""

from __future__ import annotations

import logging
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WATCHLIST_PATH = PROJECT_ROOT / "watchlist.yaml"
WATCHLISTS_DIR = PROJECT_ROOT / "watchlists"

DEFAULT_RSI_OVERSOLD = 30.0
DEFAULT_RSI_OVERBOUGHT = 70.0

logger = logging.getLogger(__name__)

AssetClass = Literal["stock", "etf", "etc"]


class AssetClassName(StrEnum):
    STOCK = "stock"
    ETF = "etf"
    ETC = "etc"


ASSET_CLASS_FILES: dict[AssetClass, str] = {
    "stock": "stock.yaml",
    "etf": "etf.yaml",
    "etc": "etc.yaml",
}

ASSET_CLASS_LABELS: dict[AssetClass, str] = {
    "stock": "Stocks",
    "etf": "ETFs",
    "etc": "ETCs",
}


class WatchlistAlerts(BaseModel):
    rsi_oversold: float = DEFAULT_RSI_OVERSOLD
    rsi_overbought: float = DEFAULT_RSI_OVERBOUGHT


class WatchlistEntry(BaseModel):
    ticker: str
    name: str
    asset_class: AssetClass = "stock"
    alerts: WatchlistAlerts = Field(default_factory=WatchlistAlerts)

    @property
    def rsi_oversold(self) -> float:
        return self.alerts.rsi_oversold

    @property
    def rsi_overbought(self) -> float:
        return self.alerts.rsi_overbought


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3:8b"
    OLLAMA_NUM_CTX: int = 8192
    OLLAMA_NUM_PREDICT: int = 512
    OLLAMA_ADVISOR_NUM_CTX: int = 6144
    OLLAMA_ADVISOR_NUM_PREDICT: int = 1024
    OLLAMA_ADVISOR_REASONING: bool = False

    PIA_LLM_PROVIDER: str = "ollama"
    PIA_LLM_MONITOR_PROVIDER: str = ""
    PIA_LLM_ADVISOR_PROVIDER: str = ""
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    # SPEC / Phase 5 aliases — mapped onto OPENAI_* in model_validator
    LLM_BASE_URL: str = ""
    VLLM_MODEL: str = ""

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    EMAIL_SMTP_HOST: str = "smtp.gmail.com"
    EMAIL_SMTP_PORT: int = 587
    EMAIL_ADDRESS: str = ""
    EMAIL_PASSWORD: str = ""
    EMAIL_RECIPIENT: str = ""

    RSS_FEEDS: str = (
        "https://feeds.content.dowjones.io/public/rss/mw_topstories,"
        "https://feeds.bbci.co.uk/news/business/rss.xml,"
        "https://news.google.com/rss/search?q=stock+market&hl=en-US&gl=US&ceid=US:en"
    )

    TIMEZONE: str = "Europe/Rome"
    SKIP_LOW_CONFIDENCE: bool = True
    MAX_TICKERS_PER_NOTIFICATION: int = 10
    MAX_NEWS_HEADLINES_PER_TICKER: int = 5
    MAX_NEWS_HEADLINES_TOTAL: int = 20
    EMAIL_ENABLED: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_TO_CONSOLE: bool = False
    ADVISOR_STALE_STATE_HOURS: float = 2.0
    ADVISOR_NEWS_WINDOW_HOURS: int = 48
    ADVISOR_NEWS_HEADLINES_PER_TICKER: int = 3
    ADVISOR_HISTORY_MAX_TURNS: int = 10
    ADVISOR_FETCH_QUOTES: bool = True
    ADVISOR_FETCH_FUNDAMENTALS: bool = False
    ADVISOR_ADHOC_ANALYSIS: bool = False
    ADVISOR_ADHOC_MAX_TICKERS: int = 3
    ADVISOR_SCAN_ENABLED: bool = False
    ADVISOR_SCAN_MAX_TICKERS: int = 150
    ADVISOR_SCAN_CONCURRENCY: int = 12
    ADVISOR_SCAN_UNIVERSE_PATH: str = "data/advisor_scan_universe.yaml"
    PROACTIVE_BRIEF_ENABLED: bool = False
    PROACTIVE_BRIEF_VIA: str = "telegram"
    PROACTIVE_BRIEF_SKIP_IF_NOTIFY: bool = False

    PIA_WEB_HOST: str = "127.0.0.1"
    PIA_WEB_PORT: int = 8765
    PIA_WEB_TOKEN: str = ""

    # In-process Monitor schedule (pia-web / pia-bot). Set false under K8s CronJobs or Ofelia.
    PIA_MONITOR_SCHEDULER: bool = True

    PIA_OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://127.0.0.1:18889"
    OTEL_SERVICE_NAME: str = "pia"

    @property
    def rss_feed_list(self) -> list[str]:
        return [feed.strip() for feed in self.RSS_FEEDS.split(",") if feed.strip()]

    @property
    def proactive_brief_channels(self) -> set[str]:
        value = self.PROACTIVE_BRIEF_VIA.strip().lower()
        if value == "both":
            return {"telegram", "email"}
        if value in {"telegram", "email"}:
            return {value}
        return set()

    @property
    def web_auth_required(self) -> bool:
        return bool(self.PIA_WEB_TOKEN.strip())

    @model_validator(mode="after")
    def apply_openai_aliases(self) -> Self:
        """Map LLM_BASE_URL → OPENAI_BASE_URL and VLLM_MODEL → OPENAI_MODEL."""
        if self.LLM_BASE_URL.strip() and not self.OPENAI_BASE_URL.strip():
            self.OPENAI_BASE_URL = self.LLM_BASE_URL.strip()
        if self.VLLM_MODEL.strip():
            self.OPENAI_MODEL = self.VLLM_MODEL.strip()
        return self

    def resolved_monitor_provider(self) -> str:
        return (self.PIA_LLM_MONITOR_PROVIDER or self.PIA_LLM_PROVIDER or "ollama").strip().lower()

    def resolved_advisor_provider(self) -> str:
        return (self.PIA_LLM_ADVISOR_PROVIDER or self.PIA_LLM_PROVIDER or "ollama").strip().lower()


def _parse_class_file(path: Path, asset_class: AssetClass) -> list[WatchlistEntry]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    items = raw.get("entries")
    if not isinstance(items, list):
        items = []
    entries: list[WatchlistEntry] = []
    for item in items:
        data = dict(item)
        data["asset_class"] = asset_class
        entries.append(WatchlistEntry.model_validate(data))
    return entries


def _load_legacy_watchlist(path: Path) -> list[WatchlistEntry]:
    """Load deprecated root watchlist.yaml (stocks + etfs sections)."""
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    entries: list[WatchlistEntry] = []
    for section, asset_class in (("stocks", "stock"), ("etfs", "etf"), ("etcs", "etc")):
        for item in raw.get(section, []) or []:
            data = dict(item)
            data["asset_class"] = asset_class
            entries.append(WatchlistEntry.model_validate(data))
    return entries


def load_watchlists(directory: Path | None = None) -> list[WatchlistEntry]:
    """Load stocks, ETFs, and ETCs from watchlists/*.yaml."""
    watchlists_dir = directory or WATCHLISTS_DIR
    entries: list[WatchlistEntry] = []

    if watchlists_dir.is_dir():
        for asset_class, filename in ASSET_CLASS_FILES.items():
            entries.extend(_parse_class_file(watchlists_dir / filename, asset_class))

    if not entries and DEFAULT_WATCHLIST_PATH.exists():
        logger.warning(
            "Using deprecated %s — migrate to watchlists/{stock,etf,etc}.yaml",
            DEFAULT_WATCHLIST_PATH,
        )
        entries = _load_legacy_watchlist(DEFAULT_WATCHLIST_PATH)

    return entries


def load_watchlist(path: Path | None = None) -> list[WatchlistEntry]:
    """Load watchlist entries (all asset classes).

    ``path`` is ignored when ``watchlists/`` exists; kept for call-site compatibility.
    """
    if path is not None and path == DEFAULT_WATCHLIST_PATH:
        return load_watchlists()
    if path is not None and path.exists():
        # Single-file override: treat as legacy multi-section
        return _load_legacy_watchlist(path)
    return load_watchlists()


def by_class(entries: list[WatchlistEntry], asset_class: AssetClass) -> list[WatchlistEntry]:
    """Filter watchlist entries by asset class."""
    return [entry for entry in entries if entry.asset_class == asset_class]


def asset_class_for_ticker(entries: list[WatchlistEntry], ticker: str) -> AssetClass | None:
    """Return asset class for a ticker, or None if not on the watchlist."""
    key = ticker.upper()
    for entry in entries:
        if entry.ticker.upper() == key or entry.ticker.upper().split(".")[0] == key.split(".")[0]:
            return entry.asset_class
    return None


def watchlist_counts(entries: list[WatchlistEntry] | None = None) -> dict[AssetClass, int]:
    """Return counts per asset class."""
    items = entries if entries is not None else load_watchlists()
    return {
        "stock": len(by_class(items, "stock")),
        "etf": len(by_class(items, "etf")),
        "etc": len(by_class(items, "etc")),
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
