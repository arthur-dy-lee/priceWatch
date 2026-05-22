"""Pluggable LLM front-end for parsing natural language → intent JSON.

Backends:
  ollama     local, no API key — default
  anthropic  Claude API
  openai     OpenAI API

Selected via PRICEWATCH_NLU_BACKEND env var, overridable per-call.

All backends accept the same `messages` list shape (OpenAI-style),
so the prompt module is shared.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx
from loguru import logger

from ..settings import settings
from ..sources.registry import all_registered
from .prompt import build_messages
from .schemas import validate_intent


_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)
_FIRST_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _strip_to_json(raw: str) -> str:
    """LLMs sometimes wrap output in ```json ... ``` or add prose. Cut to braces."""
    raw = raw.strip()
    m = _FENCE_RE.search(raw)
    if m:
        raw = m.group(1).strip()
    m = _FIRST_JSON_OBJ_RE.search(raw)
    if m:
        return m.group(0)
    return raw


# ---------------------------------------------------------------- backends


async def _call_ollama(messages: list[dict]) -> str:
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0},
        "format": "json",
    }
    # Ollama is local — bypass any HTTP/SOCKS proxy in env (trust_env=False)
    # so users with ALL_PROXY etc don't need httpx[socks] just to hit 127.0.0.1.
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        r = await client.post(f"{settings.ollama_host.rstrip('/')}/api/chat", json=payload)
        r.raise_for_status()
        return r.json()["message"]["content"]


async def _call_anthropic(messages: list[dict]) -> str:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is empty")
    # Anthropic API splits system from messages.
    system = ""
    chat: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            chat.append({"role": m["role"], "content": m["content"]})
    payload = {
        "model": settings.anthropic_model,
        "max_tokens": 1024,
        "temperature": 0,
        "system": system,
        "messages": chat,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        r.raise_for_status()
        data = r.json()
        return "".join(block.get("text", "") for block in data.get("content", []))


async def _call_openai(messages: list[dict]) -> str:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is empty")
    payload = {
        "model": settings.openai_model,
        "temperature": 0,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


_BACKENDS = {
    "ollama": _call_ollama,
    "anthropic": _call_anthropic,
    "openai": _call_openai,
}


# ---------------------------------------------------------------- public API


async def parse_intent(text: str, *, backend: str | None = None) -> dict[str, Any]:
    """Parse free-form text into a validated priceWatch intent dict.

    Raises ValueError if the LLM output is unusable.
    """
    backend = (backend or settings.pricewatch_nlu_backend or "ollama").lower()
    if backend not in _BACKENDS:
        raise ValueError(f"unknown NLU backend {backend!r}; pick one of {list(_BACKENDS)}")
    messages = build_messages(text, all_registered())
    logger.debug(f"nlu: calling {backend} for parse")
    raw = await _BACKENDS[backend](messages)
    raw_json = _strip_to_json(raw)
    try:
        obj = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"backend returned non-JSON: {raw[:300]!r}") from e
    return validate_intent(obj)
