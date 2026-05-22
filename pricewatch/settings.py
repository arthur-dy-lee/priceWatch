from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    pricewatch_db_path: str = "data/pricewatch.db"
    pricewatch_log_level: str = "INFO"
    pricewatch_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15"
    )

    @property
    def db_path(self) -> Path:
        p = Path(self.pricewatch_db_path)
        return p if p.is_absolute() else PROJECT_ROOT / p


settings = Settings()
