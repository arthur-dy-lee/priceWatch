"""CLI: introspection + manual triggers.

  pricewatch run                    # start the scheduler (same as `python -m pricewatch.main`)
  pricewatch fetch --source NAME    # one-shot fetch, store, exit
  pricewatch fields [--source NAME] # show available fields for a source (or all)
  pricewatch test-rule "EXPR"       # dry-run a rule expression against current data
  pricewatch history --source NAME  # tail recent snapshots
  pricewatch list-sources           # list registered source types and configured sources
"""
from __future__ import annotations

import asyncio
import json

import click
from loguru import logger

from . import main as main_module
from .config_loader import load_config
from .rules.derivers import SourceView, fields_for
from .rules.engine import Rule, RuleEngine
from .signals import SignalKind
from .sources.registry import all_registered, get_source_class
from .storage import get_db


@click.group()
def cli() -> None:
    """priceWatch — local sentinel for prices, stocks, and odds."""


@cli.command()
def run() -> None:
    """Start the scheduler loop."""
    main_module.main()


@cli.command("list-sources")
def list_sources_cmd() -> None:
    """Show registered source types and configured sources."""
    click.echo("Registered source types:")
    for t in all_registered():
        click.echo(f"  - {t}")
    cfg = load_config()
    click.echo("\nConfigured sources:")
    for s in cfg.sources:
        click.echo(f"  - {s.name} (type={s.type}, interval={s.cfg.get('interval', '1h')})")


@cli.command()
@click.option("--source", required=True, help="Configured source name")
@click.option("--debug", is_flag=True, help="Dump raw HTML for debugging")
def fetch(source: str, debug: bool) -> None:
    """One-shot fetch a source and store the snapshot."""
    cfg = load_config()
    s = next((x for x in cfg.sources if x.name == source), None)
    if s is None:
        raise click.ClickException(f"no such configured source: {source}")
    if debug:
        s.cfg["debug"] = True
    cls = get_source_class(s.type)
    inst = cls(name=s.name, cfg=s.cfg)

    async def _go():
        sig = await inst.fetch()
        get_db().insert_snapshot(sig)
        click.echo(f"{sig.source}  value={sig.value} {sig.currency or ''}  ts={sig.ts.isoformat()}")
        if sig.meta:
            click.echo(f"  meta: {json.dumps(sig.meta, ensure_ascii=False)}")

    asyncio.run(_go())


@cli.command()
@click.option("--source", default=None, help="Show fields for one source (default: all known)")
def fields(source: str | None) -> None:
    """Show derived fields available on a source, with current values."""
    db = get_db()
    targets: list[tuple[str, SignalKind]] = []
    if source:
        kind = db.kind_of(source)
        if kind is None:
            raise click.ClickException(
                f"no snapshots yet for '{source}'. Run `pricewatch fetch --source {source}` first."
            )
        targets.append((source, kind))
    else:
        for name in db.known_sources():
            k = db.kind_of(name)
            if k is not None:
                targets.append((name, k))
        if not targets:
            click.echo("No snapshots yet. Run `pricewatch fetch --source <name>` first.")
            return

    for name, kind in targets:
        click.echo(f"\nSource: {name}  (kind={kind.value})")
        view = SourceView(db, name, kind)
        for f in fields_for(kind):
            try:
                v = getattr(view, f)
            except Exception as e:
                v = f"<err: {e}>"
            click.echo(f"  {f:24s} = {v}")


@cli.command("test-rule")
@click.argument("expr")
@click.option("--name", default="ad-hoc", help="Rule name (for snapshot output only)")
def test_rule(expr: str, name: str) -> None:
    """Dry-run an expression. Does NOT consult cooldown — pure predicate test."""
    db = get_db()
    source_kinds = {n: db.kind_of(n) or SignalKind.PRICE for n in db.known_sources()}
    if not source_kinds:
        raise click.ClickException("no sources have snapshots yet — fetch first")
    engine = RuleEngine(db, source_kinds)
    rule = Rule(name=name, when=expr)
    results = engine.evaluate([rule])
    res = results[0]
    mark = "TRUE " if res.triggered else "FALSE"
    click.echo(f"[{mark}] {res.reason}")
    if res.value_repr:
        click.echo(f"   {res.value_repr}")


@cli.command()
@click.option("--source", required=True)
@click.option("-n", "limit", default=20, help="Number of rows")
def history(source: str, limit: int) -> None:
    """Tail recent snapshots for one source."""
    rows = get_db().latest_n(source, limit)
    if not rows:
        click.echo(f"no snapshots for {source}")
        return
    for r in reversed(rows):  # chronological
        click.echo(f"{r['ts']}  {r['value']:>10}  {r['currency'] or '':3}")


if __name__ == "__main__":
    cli()
