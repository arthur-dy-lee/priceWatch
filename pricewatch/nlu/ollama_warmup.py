"""Pin the NLU model in Ollama's GPU memory so the first /parse isn't slow.

Adapted from /Users/arthur.lee/codes/AIFeed/automation/ollama_utils.py — same
strategy (check /api/ps, evict non-targets, stream warmup chat, keep_alive=24h)
but async + httpx + scoped to priceWatch's single model.

Call sites:
  * pricewatch run        (main.py invokes warmup_ollama at startup, fire-and-forget)
  * pricewatch warmup     (CLI for manual reheat after a long idle period)

Never raises — failures are logged and the daemon keeps running. The first
real /parse call will pay the cold-load cost if warmup didn't take.
"""
from __future__ import annotations

import json
import time

import httpx
from loguru import logger

from ..settings import settings

KEEP_ALIVE = "24h"
WARMUP_TIMEOUT_S = 420   # 7 min — matches AIFeed's setting; 35B models can be slow to swap in


def _client() -> httpx.AsyncClient:
    # trust_env=False keeps loopback off SOCKS/HTTP proxy.
    return httpx.AsyncClient(timeout=30, trust_env=False)


async def _loaded_models(base_url: str) -> list[dict]:
    try:
        async with _client() as c:
            r = await c.get(f"{base_url}/api/ps")
            r.raise_for_status()
            return r.json().get("models", []) or []
    except Exception as e:
        logger.warning(f"ollama: /api/ps failed: {e!r}")
        return []


async def _unload(base_url: str, model_name: str) -> None:
    """keep_alive=0 evicts the model from GPU immediately."""
    try:
        async with _client() as c:
            await c.post(f"{base_url}/api/generate",
                         json={"model": model_name, "keep_alive": 0})
    except Exception as e:
        logger.debug(f"ollama: unload {model_name} failed (non-fatal): {e!r}")


async def _refresh_keep_alive(base_url: str, model_name: str) -> None:
    """Touch a loaded model to push its keep_alive deadline forward."""
    try:
        async with _client() as c:
            await c.post(f"{base_url}/api/generate",
                         json={"model": model_name, "keep_alive": KEEP_ALIVE})
    except Exception as e:
        logger.debug(f"ollama: keep_alive refresh failed: {e!r}")


async def _warm_load(base_url: str, model_name: str) -> bool:
    """Stream a one-token chat so we know the model is actually loaded."""
    start = time.monotonic()
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "say ok"}],
        "stream": True,
        "think": False,
        "keep_alive": KEEP_ALIVE,
        "options": {"num_ctx": 2048},
    }
    try:
        async with httpx.AsyncClient(timeout=WARMUP_TIMEOUT_S, trust_env=False) as c:
            async with c.stream("POST", f"{base_url}/api/chat", json=payload) as r:
                r.raise_for_status()
                async for raw in r.aiter_lines():
                    if not raw:
                        continue
                    try:
                        if json.loads(raw).get("done"):
                            break
                    except json.JSONDecodeError:
                        continue
        elapsed = time.monotonic() - start
        logger.info(f"ollama: model {model_name!r} ready ({elapsed:.1f}s)")
        return True
    except Exception as e:
        elapsed = time.monotonic() - start
        logger.warning(
            f"ollama: warmup of {model_name!r} failed after {elapsed:.1f}s: {e!r}. "
            "If something else is competing for VRAM, the first /parse will reload."
        )
        return False


# ---------------------------------------------------------------- public


async def warmup_ollama(*, evict_others: bool = True) -> bool:
    """Ensure the NLU model is loaded in Ollama's GPU memory.

    Returns True if the model is loaded (or was already loaded), False if
    warmup failed. Never raises.

    No-op when the configured NLU backend isn't ollama — there's nothing to
    warm up for cloud APIs.
    """
    if (settings.pricewatch_nlu_backend or "").lower() != "ollama":
        logger.debug("ollama: NLU backend isn't ollama — skipping warmup")
        return True

    base_url = settings.ollama_host.rstrip("/")
    target = settings.ollama_model
    logger.info(f"ollama: ensuring model {target!r} is loaded on {base_url}")

    loaded = await _loaded_models(base_url)
    loaded_names = {m.get("name", "") for m in loaded}

    is_loaded = any(
        name.startswith(target) or target.startswith(name)
        for name in loaded_names
    )

    if is_loaded:
        logger.info(f"ollama: {target!r} already loaded — refreshing keep_alive={KEEP_ALIVE}")
        await _refresh_keep_alive(base_url, target)
        return True

    if evict_others:
        for m in loaded:
            name = m.get("name", "")
            if name and not (name.startswith(target) or target.startswith(name)):
                vram_gb = m.get("size_vram", 0) / (1024 ** 3)
                logger.info(f"ollama: evicting {name!r} ({vram_gb:.1f}GB) to free VRAM")
                await _unload(base_url, name)

    return await _warm_load(base_url, target)
