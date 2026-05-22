from __future__ import annotations

import os

import httpx
from loguru import logger

from ..settings import settings
from .base import Notifier


class TelegramNotifier(Notifier):
    """Sends via Bot API. Credentials default to env vars on Settings."""

    def __init__(self, bot_token_env: str = "TELEGRAM_BOT_TOKEN",
                 chat_id_env: str = "TELEGRAM_CHAT_ID") -> None:
        self.token = os.getenv(bot_token_env) or settings.telegram_bot_token
        self.chat_id = os.getenv(chat_id_env) or settings.telegram_chat_id

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
