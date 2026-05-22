from __future__ import annotations

import os

import httpx
from loguru import logger

from ..settings import settings
from .base import Notifier


class TelegramNotifier(Notifier):
    """Sends via Bot API.

    Accepts either the new shape:
        token: "..."       # literal string (may come from ${VAR} expansion)
        chat_id: "..."

    or the legacy shape (kept for backward-compat):
        bot_token_env: TELEGRAM_BOT_TOKEN
        chat_id_env: TELEGRAM_CHAT_ID
    """

    def __init__(self, **kwargs) -> None:
        token = kwargs.get("token")
        chat_id = kwargs.get("chat_id")

        if not token and "bot_token_env" in kwargs:
            token = os.getenv(kwargs["bot_token_env"], "") or settings.telegram_bot_token
        if not chat_id and "chat_id_env" in kwargs:
            chat_id = os.getenv(kwargs["chat_id_env"], "") or settings.telegram_chat_id

        # Fallback to Settings defaults if still empty
        self.token = (token or "").strip() or settings.telegram_bot_token
        self.chat_id = str(chat_id or "").strip() or settings.telegram_chat_id

    async def send(self, title: str, body: str) -> None:
        if not self.token or not self.chat_id:
            logger.warning("telegram: missing token/chat_id, skipping send")
            return
        text = f"*{title}*\n{body}" if title else body
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"},
            )
            if r.status_code >= 400:
                logger.error(f"telegram send failed {r.status_code}: {r.text}")
            r.raise_for_status()
