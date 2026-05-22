from .base import Notifier
from .macos import MacOSNotifier
from .telegram import TelegramNotifier

__all__ = ["Notifier", "TelegramNotifier", "MacOSNotifier", "build_notifiers"]


def build_notifiers(cfg: dict) -> dict[str, Notifier]:
    """Read the 'notifiers' block of config.yaml -> name -> Notifier instance."""
    out: dict[str, Notifier] = {}
    for name, params in (cfg or {}).items():
        params = params or {}
        if name == "telegram":
            out[name] = TelegramNotifier(**params)
        elif name == "macos":
            out[name] = MacOSNotifier(**params)
        else:
            raise ValueError(f"unknown notifier: {name}")
    return out
