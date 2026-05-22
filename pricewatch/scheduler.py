"""APScheduler wiring. One async job per source, fixed interval from cfg."""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from .rules.derivers import parse_duration
from .sources.base import Source


def build_scheduler(sources: list[Source], on_fetch) -> AsyncIOScheduler:
    """Returns a scheduler. `on_fetch(source)` is the per-tick coroutine."""
    sched = AsyncIOScheduler()
    for src in sources:
        delta = parse_duration(src.interval)
        sched.add_job(
            on_fetch,
            trigger=IntervalTrigger(seconds=delta.total_seconds()),
            args=(src,),
            id=f"src:{src.name}",
            next_run_time=None,  # we'll trigger one immediate run at startup separately
            max_instances=1,
            coalesce=True,
        )
        logger.info(f"scheduled source '{src.name}' every {src.interval}")
    return sched
