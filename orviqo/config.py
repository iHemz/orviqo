"""Application configuration — the single source of truth for settings.

Values load from the environment (and a local ``.env``). ``bootstrap()`` is the
composition root's first call: it fails fast when the configured model's API key
is missing and exports it so downstream libraries (Pydantic AI's provider clients,
which read ``os.environ``) can see a key that otherwise only lived in ``.env``.
"""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


# The API key each supported model provider needs, by Pydantic AI model prefix.
_PROVIDER_KEYS = {"anthropic": "anthropic_api_key", "google": "google_api_key"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Only the key for the configured provider is required.
    anthropic_api_key: str = ""
    google_api_key: str = ""  # Gemini, from Google AI Studio (has a free tier)

    # Pydantic AI provider strings. Gemini Flash is the default: it has a free
    # tier and handles the structured intake decision well. Any provider in
    # _PROVIDER_KEYS works, e.g. anthropic:claude-haiku-4-5.
    orviqo_intake_model: str = "google:gemini-flash-latest"
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

    # The Orviqo business number as people dial it (e.g. +234 803 123 4567). Public,
    # not a secret: it powers the /start click-to-chat link. Empty = /start is off.
    whatsapp_display_number: str = ""

    # Public web demo caps (messages): per browser session, and per day across all
    # sessions, so a public page can't exhaust a free-tier LLM quota.
    demo_session_limit: int = 30
    demo_daily_limit: int = 300

    # Shared secret the scheduler sends to trigger the collections run
    # (Vercel Cron sends it as a Bearer token). Empty = the cron route is off.
    cron_secret: str = ""

    # Debtor-chasing: the Meta-approved template used to message a debtor outside
    # the 24h window. Empty = chasing off (the worker skips it) until registered.
    whatsapp_chase_template: str = ""
    whatsapp_template_lang: str = "en_US"

    def llm_key(self) -> tuple[str, str]:
        """The (env var name, value) of the API key the intake model needs."""
        provider = self.orviqo_intake_model.split(":", 1)[0]
        field = _PROVIDER_KEYS.get(provider)
        if field is None:
            supported = ", ".join(_PROVIDER_KEYS)
            raise ConfigError(
                f"Unsupported model provider '{provider}' in ORVIQO_INTAKE_MODEL "
                f"(supported: {supported})."
            )
        return field.upper(), getattr(self, field)

    def require_llm_key(self) -> None:
        name, value = self.llm_key()
        if not value:
            raise ConfigError(
                f"{name} is not set (needed for {self.orviqo_intake_model}). Copy "
                f".env.example to .env and add your key, or export {name} in your shell."
            )


settings = Settings()


def bootstrap() -> Settings:
    """Validate config and expose the API key to downstream libraries.

    Call once, at the start of an entry point (CLI, API factory) — never at
    import time, so importing a module stays free of side effects.
    """
    settings.require_llm_key()
    name, value = settings.llm_key()
    os.environ.setdefault(name, value)
    return settings
