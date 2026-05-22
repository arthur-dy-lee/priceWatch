"""Entry point: load config → schedule sources → on each tick: fetch, store, evaluate, notify."""
from __future__ import annotations

import asyncio
import sys

from loguru import logger

from .config_loader import load_config
from .notifiers import build_notifiers
from .rules.engine import RuleEngine
from .settings import settings
from .signals import SignalKind
from .sources.base import Source
from .sources.registry import get_source_class
from .scheduler import build_scheduler
from .storage import get_db


def _setup_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level=settings.pricewatch_log_level)
    logger.add("logs/pricewatch.log", level="DEBUG", rotation="10 MB", retention=5)


def _build_sources(cfg) -> list[Source]:
    out = []
    for s in cfg.sources:
        cls = get_source_class(s.type)
        out.append(cls(name=s.name, cfg=s.cfg))
    return out


async def _run():
    _setup_logging()
    cfg = load_config()
    db = get_db()
    sources = _build_sources(cfg)
    notifiers = build_notifiers(cfg.notifiers)

    # Map source name -> SignalKind for the rule engine.
    source_kinds = {s.name: s.kind for s in sources}
    engine = RuleEngine(db, source_kinds)

    async def on_fetch(src: Source):
        try:
            sig = await src.fetch()
            db.insert_snapshot(sig)
            logger.info(f"[{src.name}] {sig.value} {sig.currency or ''} @ {sig.ts.isoformat()}")
        except Exception as e:
            logger.exception(f"[{src.name}] fetch failed: {e!r}")
            return

        # After every fetch, re-evaluate rules that mention this source.
        results = engine.evaluate(cfg.rules)
        for res in results:
            if not res.triggered:
                continue
            logger.warning(f"RULE FIRED: {res.rule.name} — {res.value_repr}")
            db.record_fire(res.rule.name, {"reason": res.reason})
            await _notify(res, notifiers)

    sched = build_scheduler(sources, on_fetch)
    sched.start()

    # Kick off one immediate fetch for each source so we're not waiting an hour.
    for src in sources:
        asyncio.create_task(on_fetch(src))

    logger.info("priceWatch running. Ctrl-C to stop.")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("shutting down")
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
