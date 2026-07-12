"""Settings loaded from environment / .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""

    # Pydantic AI provider strings. Haiku is cheap+fast for parsing;
    # Opus 4.8 is the reasoning model for collections/reconciliation later.
    orviqo_intake_model: str = "anthropic:claude-haiku-4-5"
    orviqo_reasoning_model: str = "anthropic:claude-opus-4-8"

    whatsapp_verify_token: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""


settings = Settings()
