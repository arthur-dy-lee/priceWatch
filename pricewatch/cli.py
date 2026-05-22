"""CLI: introspection + manual triggers + mutations.

  pricewatch run                                  # start the scheduler
  pricewatch fetch --source NAME                  # one-shot fetch
  pricewatch fields [--source NAME]               # show derived field values
  pricewatch test-rule "EXPR"                     # dry-run an expression
  pricewatch history --source NAME                # tail snapshots
  pricewatch list-sources                         # registered + configured

  pricewatch add-source NAME --type T --url URL [--interval 1h] [...]
  pricewatch remove-source NAME
  pricewatch add-rule NAME --when "EXPR" [--notify telegram] [--cooldown 6h]
  pricewatch remove-rule NAME
  pricewatch reload                               # signal a running daemon to re-read config

  pricewatch parse "monitor https://... when price < $100"   # NLU intent
  pricewatch serve                                # start HTTP IPC only (no scheduler)
"""
from __future__ import annotations

import asyncio
import json

import click
from loguru import logger

from . import main as main_module
from .config_loader import load_config
from .config_ops import (
    ConfigError,
    add_rule,
    add_source,
    list_rules,
    list_sources,
    remove_rule,
    remove_source,
)
from .rules.derivers import SourceView, fields_for
from .rules.engine import Rule, RuleEngine
from .signals import SignalKind
from .sources.registry import all_registered, get_source_class
from .storage import get_db


@click.group()
def cli() -> None:
    """priceWatch — local sentinel for prices, stocks, and odds."""


# ---------------------------------------------------------------- run/serve

@cli.command()
def run() -> None:
    """Start the scheduler loop (and the IPC server alongside it)."""
    main_module.main()


@cli.command()
def serve() -> None:
    """Start the HTTP IPC server only (no scheduling, no fetching)."""
    from .ipc import serve_blocking
    serve_blocking()


@cli.command()
@click.option("--no-evict", is_flag=True, help="Don't evict other models from GPU")
def warmup(no_evict: bool) -> None:
    """Pin the NLU model in Ollama GPU memory (keep_alive=24h)."""
    from .nlu import warmup_ollama
    ok = asyncio.run(warmup_ollama(evict_others=not no_evict))
    if not ok:
        raise click.ClickException("warmup did not complete cleanly — see logs")
    click.echo("ollama: model pinned, keep_alive=24h")


# ---------------------------------------------------------------- read-only

@cli.command("list-sources")
def list_sources_cmd() -> None:
    click.echo("Registered source types:")
    for t in all_registered():
        click.echo(f"  - {t}")
    cfg = load_config()
    click.echo("\nConfigured sources:")
    for s in cfg.sources:
        click.echo(f"  - {s.name} (type={s.type}, interval={s.cfg.get('interval', '1h')})")


@cli.command("list-rules")
def list_rules_cmd() -> None:
    for r in list_rules():
        click.echo(f"  - {r['name']:30s}  when: {r.get('when')}")


@cli.command()
@click.option("--source", required=True)
@click.option("--debug", is_flag=True)
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
@click.option("--source", default=None)
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
            click.echo("No snapshots yet.")
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
@click.option("--name", default="ad-hoc")
def test_rule(expr: str, name: str) -> None:
    db = get_db()
    source_kinds = {n: db.kind_of(n) or SignalKind.PRICE for n in db.known_sources()}
    if not source_kinds:
        raise click.ClickException("no sources have snapshots yet — fetch first")
    engine = RuleEngine(db, source_kinds)
    rule = Rule(name=name, when=expr)
    res = engine.evaluate([rule])[0]
    mark = "TRUE " if res.triggered else "FALSE"
    click.echo(f"[{mark}] {res.reason}")
    if res.value_repr:
        click.echo(f"   {res.value_repr}")


@cli.command()
@click.option("--source", required=True)
@click.option("-n", "limit", default=20)
def history(source: str, limit: int) -> None:
    rows = get_db().latest_n(source, limit)
    if not rows:
        click.echo(f"no snapshots for {source}")
        return
    for r in reversed(rows):
        click.echo(f"{r['ts']}  {r['value']:>10}  {r['currency'] or '':3}")


# ---------------------------------------------------------------- mutations

@cli.command("add-source")
@click.argument("name")
@click.option("--type", "type_", required=True, help="Source type (see list-sources)")
@click.option("--url", default=None)
@click.option("--sku", default=None)
@click.option("--interval", default="1h")
def add_source_cmd(name: str, type_: str, url: str | None, sku: str | None, interval: str) -> None:
    kw = {}
    if url:
        kw["url"] = url
    if sku:
        kw["sku"] = sku
    try:
        add_source(name, type_, interval=interval, **kw)
    except ConfigError as e:
        raise click.ClickException(str(e))
    click.echo(f"added source '{name}' (type={type_}, interval={interval})")
    _signal_reload_if_running()


@cli.command("remove-source")
@click.argument("name")
def remove_source_cmd(name: str) -> None:
    if remove_source(name):
        click.echo(f"removed source '{name}'")
        _signal_reload_if_running()
    else:
        raise click.ClickException(f"no source named '{name}'")


@cli.command("add-rule")
@click.argument("name")
@click.option("--when", "when_", required=True)
@click.option("--notify", multiple=True, help="Repeat: --notify telegram --notify macos")
@click.option("--cooldown", default=None)
@click.option("--debounce", default=None)
@click.option("--message", default=None)
def add_rule_cmd(name: str, when_: str, notify: tuple[str, ...],
                 cooldown: str | None, debounce: str | None, message: str | None) -> None:
    try:
        add_rule(name, when_, notify=list(notify) or None,
                 cooldown=cooldown, debounce=debounce, message=message)
    except ConfigError as e:
        raise click.ClickException(str(e))
    click.echo(f"added rule '{name}'")
    _signal_reload_if_running()


@cli.command("remove-rule")
@click.argument("name")
def remove_rule_cmd(name: str) -> None:
    if remove_rule(name):
        click.echo(f"removed rule '{name}'")
        _signal_reload_if_running()
    else:
        raise click.ClickException(f"no rule named '{name}'")


@cli.command()
def reload() -> None:
    """Touch config.yaml so a running daemon picks up changes via the watcher."""
    from .config_loader import CONFIG_PATH
    CONFIG_PATH.touch()
    click.echo("touched config.yaml (running daemon, if any, will reload)")


# ---------------------------------------------------------------- NLU

@cli.command()
@click.argument("text", nargs=-1)
@click.option("--backend", default=None, help="ollama | anthropic | openai (default from .env)")
@click.option("--apply/--no-apply", default=False, help="Apply the parsed intent immediately")
def parse(text: tuple[str, ...], backend: str | None, apply: bool) -> None:
    """Natural-language → structured intent. Prints proposed config diff."""
    from .nlu import parse_intent
    from .config_ops import apply_intent

    msg = " ".join(text).strip()
    if not msg:
        raise click.ClickException("nothing to parse")
    try:
        intent = asyncio.run(parse_intent(msg, backend=backend))
    except Exception as e:
        raise click.ClickException(f"NLU failed: {e!r}")
    click.echo("Parsed intent:")
    click.echo(json.dumps(intent, ensure_ascii=False, indent=2))
    if apply:
        changed = apply_intent(intent)
        click.echo("\nApplied:")
        click.echo(json.dumps(changed, ensure_ascii=False, indent=2))
        _signal_reload_if_running()
    else:
        click.echo("\n(dry-run — pass --apply to write to config.yaml)")


# ---------------------------------------------------------------- helpers

def _signal_reload_if_running() -> None:
    """Touch the config so a running daemon's watchdog picks it up."""
    from .config_loader import CONFIG_PATH
    try:
        CONFIG_PATH.touch()
    except Exception as e:
        logger.debug(f"config touch failed (probably no daemon running): {e}")


if __name__ == "__main__":
    cli()
