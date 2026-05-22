from __future__ import annotations

import asyncio
import shlex

from .base import Notifier


class MacOSNotifier(Notifier):
    """Local Notification Center via osascript. Useful as a no-network fallback."""

    async def send(self, title: str, body: str) -> None:
        script = (
            f'display notification {shlex.quote(body)} '
            f'with title {shlex.quote(title or "priceWatch")}'
        )
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
