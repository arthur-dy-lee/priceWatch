"""FastAPI app exposing config mutations + state queries to local callers.

Auth: when PRICEWATCH_IPC_TOKEN is set, every request must carry
      `Authorization: Bearer <token>`. If empty, no auth (loopback only).

Endpoints:
  GET  /healthz
  GET  /sources                        list configured sources (yaml view)
  GET  /sources/{name}/snapshot        derived field values
  POST /sources                        body: {name, type, url?, sku?, interval?}
  DELETE /sources/{name}
  GET  /rules
  POST /rules                          body: {name, when, notify, cooldown?, debounce?, message?}
  DELETE /rules/{name}
  POST /parse                          body: {text, backend?, apply?}
  POST /reload                         touch config.yaml to trigger watcher

Designed to be called by matrixApps PM bot once it grows a priceWatch agent.
"""
from __future__ import annotations

from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status
from loguru import logger
from pydantic import BaseModel

from .config_loader import CONFIG_PATH, load_config
from .config_ops import (
    ConfigError,
    add_rule,
    add_source,
    apply_intent,
    list_rules,
    list_sources,
    remove_rule,
    remove_source,
)
from .rules.derivers import SourceView, fields_for
from .settings import settings
from .signals import SignalKind
from .storage import get_db


# ---------------------------------------------------------------- request models


class SourceCreate(BaseModel):
    name: str
    type: str
    url: str | None = None
    sku: str | None = None
    interval: str = "1h"


class RuleCreate(BaseModel):
    name: str
    when: str
    notify: list[str] = []
    cooldown: str | None = None
    debounce: str | None = None
    message: str | None = None


class ParseRequest(BaseModel):
    text: str
    backend: str | None = None
    apply: bool = False


# ---------------------------------------------------------------- auth


def _check_token(authorization: str | None = Header(default=None)) -> None:
    expected = settings.pricewatch_ipc_token
    if not expected:
        return  # auth disabled
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bad token")


# ---------------------------------------------------------------- app


def build_app(reloader=None) -> FastAPI:
    """Build a FastAPI app. `reloader` is optional; if given, /reload calls into it."""
    app = FastAPI(title="priceWatch IPC", version="0.2")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/sources", dependencies=[Depends(_check_token)])
    def get_sources() -> list[dict]:
        return list_sources()

    @app.get("/sources/{name}/snapshot", dependencies=[Depends(_check_token)])
    def get_snapshot(name: str) -> dict:
        db = get_db()
        kind = db.kind_of(name)
        if kind is None:
            raise HTTPException(404, f"no snapshots yet for '{name}'")
        view = SourceView(db, name, kind)
        out: dict[str, Any] = {"source": name, "kind": kind.value, "fields": {}}
        for f in fields_for(kind):
            try:
                out["fields"][f] = getattr(view, f)
            except Exception as e:
                out["fields"][f] = f"<err: {e}>"
        return out

    @app.post("/sources", status_code=201, dependencies=[Depends(_check_token)])
    def post_source(body: SourceCreate) -> dict:
        kw = {k: v for k, v in body.model_dump().items()
              if k not in ("name", "type", "interval") and v is not None}
        try:
            add_source(body.name, body.type, interval=body.interval, **kw)
        except ConfigError as e:
            raise HTTPException(400, str(e))
        _touch_config()
        return {"ok": True, "name": body.name}

    @app.delete("/sources/{name}", dependencies=[Depends(_check_token)])
    def delete_source(name: str) -> dict:
        if not remove_source(name):
            raise HTTPException(404, f"no source named '{name}'")
        _touch_config()
        return {"ok": True}

    @app.get("/rules", dependencies=[Depends(_check_token)])
    def get_rules() -> list[dict]:
        return list_rules()

    @app.post("/rules", status_code=201, dependencies=[Depends(_check_token)])
    def post_rule(body: RuleCreate) -> dict:
        try:
            add_rule(body.name, body.when, notify=body.notify or None,
                     cooldown=body.cooldown, debounce=body.debounce, message=body.message)
        except ConfigError as e:
            raise HTTPException(400, str(e))
        _touch_config()
        return {"ok": True, "name": body.name}

    @app.delete("/rules/{name}", dependencies=[Depends(_check_token)])
    def delete_rule(name: str) -> dict:
        if not remove_rule(name):
            raise HTTPException(404, f"no rule named '{name}'")
        _touch_config()
        return {"ok": True}

    @app.post("/parse", dependencies=[Depends(_check_token)])
    async def post_parse(body: ParseRequest) -> dict:
        from .nlu import parse_intent
        try:
            intent = await parse_intent(body.text, backend=body.backend)
        except Exception as e:
            raise HTTPException(400, f"NLU failed: {e!r}")
        out = {"intent": intent}
        if body.apply:
            try:
                out["applied"] = apply_intent(intent)
                _touch_config()
            except ConfigError as e:
                raise HTTPException(400, f"apply failed: {e}")
        return out

    @app.post("/reload", dependencies=[Depends(_check_token)])
    def post_reload() -> dict:
        _touch_config()
        return {"ok": True}

    @app.get("/config", dependencies=[Depends(_check_token)])
    def get_config() -> dict:
        cfg = load_config()
        return {
            "sources": [{"name": s.name, "type": s.type, **s.cfg} for s in cfg.sources],
            "rules":   [{"name": r.name, "when": r.when, "notify": r.notify,
                         "cooldown": r.cooldown, "debounce": r.debounce} for r in cfg.rules],
            "notifiers": {k: {kk: vv for kk, vv in v.items() if "token" not in kk.lower()}
                          for k, v in cfg.notifiers.items()},
        }

    return app


def _touch_config() -> None:
    try:
        CONFIG_PATH.touch()
    except Exception as e:
        logger.debug(f"touch config failed: {e}")


# ---------------------------------------------------------------- server runners


async def run_server(app: FastAPI) -> None:
    """Run uvicorn cooperatively inside the main asyncio loop."""
    cfg = uvicorn.Config(
        app, host=settings.pricewatch_ipc_host, port=settings.pricewatch_ipc_port,
        log_level=settings.pricewatch_log_level.lower(), lifespan="off",
    )
    server = uvicorn.Server(cfg)
    logger.info(f"ipc: listening on http://{settings.pricewatch_ipc_host}:{settings.pricewatch_ipc_port}")
    await server.serve()


def serve_blocking() -> None:
    """For `pricewatch serve` — runs the IPC alone, no scheduler."""
    import asyncio
    asyncio.run(run_server(build_app()))
