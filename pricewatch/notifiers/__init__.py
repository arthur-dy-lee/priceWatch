from .base import Notifier
from .macos import MacOSNotifier
from .telegram import TelegramNotifier

__all__ = ["Notifier", "TelegramNotifier", "MacOSNotifier", "build_notifiers"]


def build_notifiers(cfg: dict) -> dict[str, Notifier]:
    """Read the 'notifiers' block of config.yaml -> name -> Notifier instance.

    Two supported config shapes per notifier (both fine):

      telegram:                    # 1) typed (preferred)
        type: telegram
        token: ${TELEGRAM_BOT_TOKEN}
        chat_id: ${TELEGRAM_CHAT_ID}

      telegram:                    # 2) legacy / shorthand — type is inferred from name
        bot_token_env: TELEGRAM_BOT_TOKEN
        chat_id_env: TELEGRAM_CHAT_ID
    """
    out: dict[str, Notifier] = {}
    for name, params in (cfg or {}).items():
        params = dict(params or {})
        kind = params.pop("type", None) or _infer_type_from_name(name)
        if kind == "telegram":
            out[name] = TelegramNotifier(**params)
        elif kind == "macos":
            out[name] = MacOSNotifier(**params)
        else:
            raise ValueError(f"unknown notifier type for '{name}': {kind!r}")
    return out


def _infer_type_from_name(name: str) -> str:
    n = name.lower()
    if n.startswith("telegram") or n == "tg":
        return "telegram"
    if n.startswith("macos") or n == "mac":
        return "macos"
    return name
