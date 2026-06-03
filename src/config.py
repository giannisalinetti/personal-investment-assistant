"""Application configuration and watchlist loading."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WATCHLIST_PATH = PROJECT_ROOT / "watchlist.yaml"

DEFAULT_RSI_OVERSOLD = 30.0
DEFAULT_RSI_OVERBOUGHT = 70.0


class WatchlistAlerts(BaseModel):
    rsi_oversold: float = DEFAULT_RSI_OVERSOLD
    rsi_overbought: float = DEFAULT_RSI_OVERBOUGHT


class WatchlistEntry(BaseModel):
    ticker: str
    name: str
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
    OLLAMA_ADVISOR_NUM_CTX: int = 16384
    OLLAMA_ADVISOR_NUM_PREDICT: int = 4096

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
    ADVISOR_NEWS_WINDOW_HOURS: int = 168
    ADVISOR_NEWS_HEADLINES_PER_TICKER: int = 8
    ADVISOR_HISTORY_MAX_TURNS: int = 20
    ADVISOR_FETCH_QUOTES: bool = True
    ADVISOR_ADHOC_ANALYSIS: bool = True
    ADVISOR_ADHOC_MAX_TICKERS: int = 3
    ADVISOR_SCAN_ENABLED: bool = True
    ADVISOR_SCAN_MAX_TICKERS: int = 150
    ADVISOR_SCAN_CONCURRENCY: int = 12
    ADVISOR_SCAN_UNIVERSE_PATH: str = "data/advisor_scan_universe.yaml"
    PROACTIVE_BRIEF_ENABLED: bool = False
    PROACTIVE_BRIEF_VIA: str = "telegram"
    PROACTIVE_BRIEF_SKIP_IF_NOTIFY: bool = False

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


def load_watchlist(path: Path | None = None) -> list[WatchlistEntry]:
    """Load and validate watchlist entries from YAML."""
    watchlist_path = path or DEFAULT_WATCHLIST_PATH
    with watchlist_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    entries: list[WatchlistEntry] = []
    for section in ("stocks", "etfs"):
        for item in raw.get(section, []):
            entries.append(WatchlistEntry.model_validate(item))
    return entries


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
