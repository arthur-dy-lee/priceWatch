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

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    fireup_notify_bot_token: str = ""

    # --- NLU ---
    pricewatch_nlu_backend: str = "ollama"
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.6:35b"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # --- IPC ---
    pricewatch_ipc_host: str = "127.0.0.1"
    pricewatch_ipc_port: int = 8765
    pricewatch_ipc_token: str = ""

    # --- Storage / runtime ---
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
