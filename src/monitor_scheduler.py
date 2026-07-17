"""In-process Monitor scheduler (APScheduler) shared by pia-web and pia-bot."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import settings
from src.run_once import VALID_RUN_TYPES, run_once
from src.state_persistence import NEXT_RUNS

logger = logging.getLogger(__name__)

_run_lock = asyncio.Lock()
_scheduler: AsyncIOScheduler | None = None
_last_status: dict[str, Any] = {
    "running": False,
    "last_run_type": None,
    "last_started_at": None,
    "last_finished_at": None,
    "last_exit_code": None,
    "last_error": None,
}


def monitor_busy() -> bool:
    return _run_lock.locked()


def monitor_status() -> dict[str, Any]:
    """Snapshot for API / status surfaces."""
    return {
        **_last_status,
        "scheduler_enabled": settings.PIA_MONITOR_SCHEDULER,
        "scheduler_running": bool(_scheduler and _scheduler.running),
        "busy": monitor_busy(),
        "next_runs": dict(NEXT_RUNS),
        "timezone": settings.TIMEZONE,
    }


async def trigger_monitor_run(*, run_type: str = "manual", wait: bool = True) -> dict[str, Any]:
    """Run Monitor under the shared lock. If busy and wait=False, return conflict."""
    if run_type not in VALID_RUN_TYPES:
        raise ValueError(f"Invalid run_type: {run_type}")

    if monitor_busy() and not wait:
        return {
            "status": "conflict",
            "message": "Monitor run already in progress",
            **monitor_status(),
        }

    async with _run_lock:
        started = datetime.now().astimezone().isoformat(timespec="seconds")
        _last_status.update(
            {
                "running": True,
                "last_run_type": run_type,
                "last_started_at": started,
                "last_error": None,
            }
        )
        logger.info("Monitor run starting run_type=%s", run_type)
        try:
            exit_code = await run_once(run_type=run_type)
            finished = datetime.now().astimezone().isoformat(timespec="seconds")
            _last_status.update(
                {
                    "running": False,
                    "last_finished_at": finished,
                    "last_exit_code": exit_code,
                }
            )
            return {
                "status": "ok" if exit_code == 0 else "error",
                "exit_code": exit_code,
                "run_type": run_type,
                **monitor_status(),
            }
        except Exception as exc:
            finished = datetime.now().astimezone().isoformat(timespec="seconds")
            _last_status.update(
                {
                    "running": False,
                    "last_finished_at": finished,
                    "last_exit_code": 1,
                    "last_error": str(exc),
                }
            )
            logger.exception("Monitor run failed run_type=%s", run_type)
            return {
                "status": "error",
                "exit_code": 1,
                "run_type": run_type,
                "message": str(exc),
                **monitor_status(),
            }


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour_s, minute_s = value.strip().split(":", 1)
    return int(hour_s), int(minute_s)


async def _scheduled_job(run_type: str) -> None:
    await trigger_monitor_run(run_type=run_type, wait=True)


def start_monitor_scheduler() -> AsyncIOScheduler | None:
    """Start APScheduler jobs when PIA_MONITOR_SCHEDULER is enabled."""
    global _scheduler
    if not settings.PIA_MONITOR_SCHEDULER:
        logger.info("Monitor scheduler disabled (PIA_MONITOR_SCHEDULER=false)")
        return None
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    tz = ZoneInfo(settings.TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)
    for run_type, hhmm in NEXT_RUNS.items():
        hour, minute = _parse_hhmm(hhmm)
        scheduler.add_job(
            _scheduled_job,
            CronTrigger(hour=hour, minute=minute, timezone=tz),
            id=f"monitor-{run_type}",
            kwargs={"run_type": run_type},
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        logger.info(
            "Scheduled Monitor %s at %s %s",
            run_type,
            hhmm,
            settings.TIMEZONE,
        )

    scheduler.start()
    _scheduler = scheduler
    logger.info("Monitor scheduler started")
    return scheduler


def stop_monitor_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Monitor scheduler stopped")
