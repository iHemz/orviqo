"""Config: the intake model's provider decides which API key is required."""

from __future__ import annotations

import pytest
from orviqo.config import ConfigError, Settings


def _settings(**values: str) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_gemini_model_needs_the_google_key() -> None:
    s = _settings(orviqo_intake_model="google:gemini-flash-latest", google_api_key="g-key")
    assert s.llm_keys() == [("GOOGLE_API_KEY", "g-key")]
    s.require_llm_keys()  # does not raise


def test_anthropic_model_needs_the_anthropic_key() -> None:
    s = _settings(orviqo_intake_model="anthropic:claude-haiku-4-5", anthropic_api_key="a-key")
    assert s.llm_keys() == [("ANTHROPIC_API_KEY", "a-key")]


def test_missing_key_names_the_variable_to_set() -> None:
    s = _settings(orviqo_intake_model="google:gemini-flash-latest", google_api_key="")
    with pytest.raises(ConfigError, match="GOOGLE_API_KEY"):
        s.require_llm_keys()


def test_unsupported_provider_is_rejected() -> None:
    with pytest.raises(ConfigError, match="Unsupported model provider"):
        _settings(orviqo_intake_model="mystery:model").llm_keys()


def test_neon_url_is_converted_for_asyncpg() -> None:
    neon = "postgresql://u:p@ep-x.eu-central-1.aws.neon.tech/orviqo?sslmode=require&channel_binding=require"
    assert _settings(database_url=neon).database_url == (
        "postgresql+asyncpg://u:p@ep-x.eu-central-1.aws.neon.tech/orviqo?ssl=require"
    )


def test_database_urls_that_already_work_are_untouched() -> None:
    for url in (
        "postgresql+asyncpg://u:p@host/orviqo?ssl=require",
        "sqlite+aiosqlite:///./orviqo.db",
    ):
        assert _settings(database_url=url).database_url == url
    assert _settings(database_url="postgres://u:p@host/db").database_url == (
        "postgresql+asyncpg://u:p@host/db"
    )


def test_a_fallback_chain_needs_each_providers_key_once() -> None:
    s = _settings(
        orviqo_intake_model=(
            "google:gemini-flash-latest, google:gemini-flash-lite-latest,anthropic:claude-haiku-4-5"
        ),
        google_api_key="g-key",
        anthropic_api_key="",
    )
    assert s.intake_models == [
        "google:gemini-flash-latest",
        "google:gemini-flash-lite-latest",
        "anthropic:claude-haiku-4-5",
    ]
    assert s.llm_keys() == [("GOOGLE_API_KEY", "g-key"), ("ANTHROPIC_API_KEY", "")]
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        s.require_llm_keys()
