"""Watch config.yaml; on change, reconcile scheduled jobs and notifier set.

Reconcile rules:
  - source removed from yaml -> kill its scheduler job
  - source added            -> schedule it (and trigger an immediate fetch)
  - source kept, interval changed -> reschedule
  - rules list is fully replaced in-memory each tick (cheap; no jobs to manage)
"""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config_loader import CONFIG_PATH, load_config
from .notifiers import build_notifiers
from .rules.derivers import parse_duration
from .signals import SignalKind
from .sources.base import Source
from .sources.registry import get_source_class


def build_source(s) -> Source:
    cls = get_source_class(s.type)
    return cls(name=s.name, cfg=s.cfg)


class ConfigReloader:
    """Owns the scheduler, the current source set, and current rule list."""

    def __init__(self, sched: AsyncIOScheduler, on_fetch: Callable, loop: asyncio.AbstractEventLoop):
        self.sched = sched
        self.on_fetch = on_fetch
        self.loop = loop
        self.sources: dict[str, Source] = {}
        self.cfg = None
        self.notifiers: dict = {}
        self.source_kinds: dict[str, SignalKind] = {}

    # ---- initial + reconciled load ----

    def apply(self, *, immediate_fetch: bool = True) -> None:
        cfg = load_config()
        new_names = {s.name for s in cfg.sources}
        old_names = set(self.sources)

        # remove
        for name in old_names - new_names:
            job_id = f"src:{name}"
            try:
                self.sched.remove_job(job_id)
            except Exception:
                pass
            self.sources.pop(name, None)
            self.source_kinds.pop(name, None)
            logger.info(f"reloader: removed source '{name}'")

        # add or update
        for sc in cfg.sources:
            existing = self.sources.get(sc.name)
            wanted_interval = sc.cfg.get("interval", "1h")
            need_add = existing is None
            need_reschedule = existing is not None and existing.interval != wanted_interval

            if need_add or need_reschedule:
                src = build_source(sc)
                delta = parse_duration(src.interval)
                job_id = f"src:{src.name}"
                try:
                    self.sched.remove_job(job_id)
                except Exception:
                    pass
                self.sched.add_job(
                    self.on_fetch,
                    trigger=IntervalTrigger(seconds=delta.total_seconds()),
                    args=(src,),
                    id=job_id,
                    max_instances=1,
                    coalesce=True,
                )
                self.sources[src.name] = src
                self.source_kinds[src.name] = src.kind
                action = "added" if need_add else "rescheduled"
                logger.info(f"reloader: {action} source '{src.name}' every {src.interval}")
                if immediate_fetch and need_add:
                    asyncio.run_coroutine_threadsafe(self.on_fetch(src), self.loop)

        self.cfg = cfg
        self.notifiers = build_notifiers(cfg.notifiers)


# ----------------------------------------------------------------------
# watchdog wiring
# ----------------------------------------------------------------------


class _Handler(FileSystemEventHandler):
    """Debounced file event handler — yaml editors often write multiple events."""

    def __init__(self, target: Path, callback: Callable[[], None], debounce_s: float = 0.4):
        self.target = target.resolve()
        self.callback = callback
        self.debounce_s = debounce_s
        self._last_fired = 0.0
        self._lock = threading.Lock()

    def on_any_event(self, event) -> None:
        try:
            p = Path(event.src_path).resolve()
        except Exception:
            return
        if p != self.target:
            return
        now = time.monotonic()
        with self._lock:
            if now - self._last_fired < self.debounce_s:
                return
            self._last_fired = now
        logger.info(f"reloader: config change detected ({event.event_type})")
        try:
            self.callback()
        except Exception as e:
            logger.exception(f"reloader: apply failed: {e!r}")


def start_watcher(reloader: ConfigReloader) -> Observer:
    """Spawn a watchdog observer that calls reloader.apply on every config change."""
    handler = _Handler(CONFIG_PATH, lambda: reloader.apply(immediate_fetch=True))
    obs = Observer()
    obs.schedule(handler, str(CONFIG_PATH.parent), recursive=False)
    obs.start()
    logger.info(f"reloader: watching {CONFIG_PATH}")
    return obs
