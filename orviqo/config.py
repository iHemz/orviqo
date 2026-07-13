"""Application configuration — the single source of truth for settings.

Values load from the environment (and a local ``.env``). ``bootstrap()`` is the
composition root's first call: it fails fast when the API key is missing and
exports it so downstream libraries (Pydantic AI's Anthropic client, which reads
``os.environ``) can see a key that otherwise only lived in ``.env``.
"""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""

    # Pydantic AI provider strings. Haiku is cheap+fast for parsing;
    # Opus 4.8 is the reasoning model for collections/reconciliation (Week 3+).
    orviqo_intake_model: str = "anthropic:claude-haiku-4-5"
    orviqo_reasoning_model: str = "anthropic:claude-opus-4-8"

    # Safety net: below this confidence a "create" falls back to asking. The agent
    # itself decides create/update/clarify, so this is a low floor, not the main gate.
    intake_confidence_threshold: float = 0.5

    # Ledger database. SQLite by default (zero setup); prod sets Postgres via
    # DATABASE_URL, e.g. postgresql+asyncpg://user:pass@host:5432/orviqo
    database_url: str = "sqlite+aiosqlite:///./orviqo.db"

    whatsapp_verify_token: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"

    # Debtor-chasing: the Meta-approved template used to message a debtor outside
    # the 24h window. Empty = chasing off (the worker skips it) until registered.
    whatsapp_chase_template: str = ""
    whatsapp_template_lang: str = "en_US"

    def require_anthropic_key(self) -> None:
        if not self.anthropic_api_key:
            raise ConfigError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key, "
                "or export ANTHROPIC_API_KEY in your shell."
            )


settings = Settings()


def bootstrap() -> Settings:
    """Validate config and expose the API key to downstream libraries.

    Call once, at the start of an entry point (CLI, API factory) — never at
    import time, so importing a module stays free of side effects.
    """
    settings.require_anthropic_key()
    os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)
    return settings
