"""Runtime Agent Skills loader (agentskills.io-compatible)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from src.config import PROJECT_ROOT, AssetClass, WatchlistEntry

logger = logging.getLogger(__name__)

SKILLS_DIR = PROJECT_ROOT / ".agents" / "skills"

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)

_TECHNICAL_HINTS = re.compile(
    r"\b(rsi|macd|ema|bollinger|indicator|overbought|oversold|signal|technical)\b",
    re.IGNORECASE,
)
_NEWS_HINTS = re.compile(
    r"\b(news|headline|announce|recent|today|yesterday|last\s+(few\s+)?days|"
    r"this\s+week|why|rise|rally|surge|jump|fall|drop|selloff|move|moving)\b",
    re.IGNORECASE,
)

_CLASS_SKILL: dict[AssetClass, str] = {
    "stock": "stock-analysis",
    "etf": "etf-analysis",
    "etc": "etc-analysis",
}


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path


def _parse_skill_md(path: Path) -> Skill | None:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if not match:
        logger.warning("Skill missing frontmatter: %s", path)
        return None
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        return None
    name = str(meta.get("name", "")).strip()
    description = str(meta.get("description", "")).strip()
    body = match.group(2).strip()
    if not name or not description:
        logger.warning("Skill missing name/description: %s", path)
        return None
    if name != path.parent.name:
        logger.warning("Skill name %r != directory %r", name, path.parent.name)
    return Skill(name=name, description=description, body=body, path=path)


@lru_cache
def discover_skills() -> dict[str, Skill]:
    """Load all skills from .agents/skills/*/SKILL.md."""
    skills: dict[str, Skill] = {}
    if not SKILLS_DIR.is_dir():
        logger.debug("No skills directory at %s", SKILLS_DIR)
        return skills
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        skill = _parse_skill_md(skill_md)
        if skill:
            skills[skill.name] = skill
    logger.info("Discovered %d agent skills", len(skills))
    return skills


def select_skills(
    *,
    mode: str,
    question: str,
    watchlist: list[WatchlistEntry],
    target_entries: list[WatchlistEntry] | None = None,
) -> list[Skill]:
    """Auto-activate skills from asset class and question intent (Advisor)."""
    catalog = discover_skills()
    selected: list[Skill] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name in seen:
            return
        skill = catalog.get(name)
        if skill:
            selected.append(skill)
            seen.add(name)

    scope = target_entries if target_entries else watchlist
    if mode == "brief":
        scope = watchlist

    classes: set[AssetClass] = {entry.asset_class for entry in scope} if scope else set()
    if not classes and mode == "ask":
        # Free-form question: infer from watchlist mentions later via target_entries
        classes = {entry.asset_class for entry in watchlist}

    for asset_class in ("stock", "etf", "etc"):
        if asset_class in classes:
            add(_CLASS_SKILL[asset_class])

    if mode == "brief" or _TECHNICAL_HINTS.search(question):
        add("market-technicals")
    if mode == "brief" or _NEWS_HINTS.search(question):
        add("news-sentiment")

    # Always include technicals for brief so signals are interpreted consistently
    if mode == "brief":
        add("market-technicals")
        add("news-sentiment")

    return selected


def select_monitor_skills(
    *,
    asset_classes: set[AssetClass] | frozenset[AssetClass] | None = None,
    watchlist: list[WatchlistEntry] | None = None,
    include_technicals: bool = False,
    include_news: bool = False,
) -> list[Skill]:
    """Lean skill set for Monitor LLM calls (class policy + optional technicals/news)."""
    catalog = discover_skills()
    selected: list[Skill] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name in seen:
            return
        skill = catalog.get(name)
        if skill:
            selected.append(skill)
            seen.add(name)

    classes: set[AssetClass] = set(asset_classes) if asset_classes else set()
    if not classes and watchlist:
        classes = {entry.asset_class for entry in watchlist}

    for asset_class in ("stock", "etf", "etc"):
        if asset_class in classes:
            add(_CLASS_SKILL[asset_class])

    if include_technicals:
        add("market-technicals")
    if include_news:
        add("news-sentiment")

    return selected


def format_skills_block(skills: list[Skill]) -> str:
    """Format activated skills for injection into an LLM prompt."""
    if not skills:
        return "No specialized skills activated."
    parts = [f"(Activated skills: {', '.join(s.name for s in skills)})"]
    for skill in skills:
        parts.append(f"\n### Skill: {skill.name}\n{skill.body}")
    return "\n".join(parts)


def format_monitor_skills_block(skills: list[Skill]) -> str:
    """Skills preamble for Monitor JSON/language calls; empty if none activated."""
    if not skills:
        return ""
    return (
        "Follow these class/policy skills for wording and asset-class correctness. "
        "Still return ONLY the required JSON / scores — do not add free-form advice.\n"
        + format_skills_block(skills)
    )


def activated_skill_names(skills: list[Skill]) -> list[str]:
    return [skill.name for skill in skills]
