"""Entry point: scheduler + hot-reload watcher + HTTP IPC, all in one loop."""
from __future__ import annotations

import asyncio
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from .reloader import ConfigReloader, start_watcher
from .rules.engine import RuleEngine
from .settings import settings
from .sources.base import Source
from .storage import get_db


def _setup_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level=settings.pricewatch_log_level)
    logger.add("logs/pricewatch.log", level="DEBUG", rotation="10 MB", retention=5)


async def _run() -> None:
    _setup_logging()
    db = get_db()
    loop = asyncio.get_running_loop()
    sched = AsyncIOScheduler()
    sched.start()

    async def on_fetch(src: Source) -> None:
        try:
            sig = await src.fetch()
            db.insert_snapshot(sig)
            logger.info(f"[{src.name}] {sig.value} {sig.currency or ''} @ {sig.ts.isoformat()}")
        except Exception as e:
            logger.exception(f"[{src.name}] fetch failed: {e!r}")
            return

        # Re-evaluate rules using the latest cfg snapshot.
        engine = RuleEngine(db, reloader.source_kinds)
        for res in engine.evaluate(reloader.cfg.rules):
            if not res.triggered:
                continue
            logger.warning(f"RULE FIRED: {res.rule.name} — {res.value_repr}")
            db.record_fire(res.rule.name, {"reason": res.reason})
            await _notify(res, reloader.notifiers)

    reloader = ConfigReloader(sched, on_fetch, loop)
    reloader.apply(immediate_fetch=True)
    observer = start_watcher(reloader)

    # Start HTTP IPC in the background.
    from .ipc import build_app, run_server
    ipc_task = asyncio.create_task(run_server(build_app(reloader)))

    logger.info("priceWatch running. Ctrl-C to stop.")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("shutting down")
    finally:
        observer.stop()
        observer.join(timeout=2)
        ipc_task.cancel()
        sched.shutdown(wait=False)


async def _notify(res, notifiers) -> None:
    title = f"⚠ {res.rule.name}"
    body = res.rule.message or f"{res.reason}\n{res.value_repr}"
    for ch in res.rule.notify:
        n = notifiers.get(ch)
        if not n:
            logger.warning(f"rule '{res.rule.name}' references unknown notifier '{ch}'")
            continue
        try:
            await n.send(title, body)
        except Exception as e:
            logger.exception(f"notifier '{ch}' failed: {e!r}")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
