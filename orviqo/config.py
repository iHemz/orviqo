"""Application configuration — the single source of truth for settings.

Values load from the environment (and a local ``.env``). ``bootstrap()`` is the
composition root's first call: it fails fast when the configured model's API key
is missing and exports it so downstream libraries (Pydantic AI's provider clients,
which read ``os.environ``) can see a key that otherwise only lived in ``.env``.
"""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def async_database_url(url: str) -> str:
    """Turn the Postgres URL a provider hands out into one SQLAlchemy async accepts.

    Neon (and most hosts) give ``postgres(ql)://...?sslmode=require&channel_binding=
    require``, the libpq form. The async driver, asyncpg, needs the
    ``postgresql+asyncpg://`` scheme and rejects both query options (``connect()
    got an unexpected keyword argument 'sslmode'``), so: swap the scheme, map
    ``sslmode`` to asyncpg's ``ssl``, and drop ``channel_binding``. Other URLs
    (SQLite, an already-async URL) pass through unchanged.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("postgres", "postgresql", "postgresql+asyncpg"):
        return url
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "sslmode":
            query.append(("ssl", value))
        elif key != "channel_binding":
            query.append((key, value))
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", query=urlencode(query)))


# The API key each supported model provider needs, by Pydantic AI model prefix.
_PROVIDER_KEYS = {"anthropic": "anthropic_api_key", "google": "google_api_key"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Only the keys for the configured providers are required.
    anthropic_api_key: str = ""
    google_api_key: str = ""  # Gemini, from Google AI Studio (has a free tier)

    # Pydantic AI model strings, comma-separated: the first is used, and each next
    # one takes over when the one before is overloaded or slow. The default is
    # Gemini Flash-Lite, then Flash (separate free-tier quotas): on the live demo
    # Flash-Lite answered in about 4s while Flash was overloaded or too slow. Any
    # provider in _PROVIDER_KEYS works, e.g. anthropic:claude-haiku-4-5.
    orviqo_intake_model: str = "google:gemini-flash-lite-latest,google:gemini-flash-latest"
    orviqo_reasoning_model: str = "anthropic:claude-opus-4-8"

    # Safety net: below this confidence a "create" falls back to asking. The agent
    # itself decides create/update/clarify, so this is a low floor, not the main gate.
    intake_confidence_threshold: float = 0.5

    # Ledger database. SQLite by default (zero setup); prod sets Postgres via
    # DATABASE_URL. Paste the provider's URL as-is: it is converted for asyncpg.
    database_url: str = "sqlite+aiosqlite:///./orviqo.db"

    whatsapp_verify_token: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"
    # Meta app secret (App settings → Basic). Verifies that webhook POSTs really
    # come from Meta. Required whenever real WhatsApp credentials are set.
    whatsapp_app_secret: str = ""

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

    @field_validator("database_url")
    @classmethod
    def _async_database_url(cls, url: str) -> str:
        return async_database_url(url)

    @property
    def intake_models(self) -> list[str]:
        """The intake model strings, in fallback order."""
        return [m.strip() for m in self.orviqo_intake_model.split(",") if m.strip()]

    def llm_keys(self) -> list[tuple[str, str]]:
        """The (env var name, value) of each API key the intake models need."""
        keys: list[tuple[str, str]] = []
        for model in self.intake_models:
            provider = model.split(":", 1)[0]
            field = _PROVIDER_KEYS.get(provider)
            if field is None:
                supported = ", ".join(_PROVIDER_KEYS)
                raise ConfigError(
                    f"Unsupported model provider '{provider}' in ORVIQO_INTAKE_MODEL "
                    f"(supported: {supported})."
                )
            key = (field.upper(), getattr(self, field))
            if key not in keys:
                keys.append(key)
        return keys

    def require_llm_keys(self) -> None:
        if not self.intake_models:
            raise ConfigError("ORVIQO_INTAKE_MODEL is empty.")
        for name, value in self.llm_keys():
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
    settings.require_llm_keys()
    for name, value in settings.llm_keys():
        os.environ.setdefault(name, value)
    return settings
