from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    # Environment variables win over .env. Names are case insensitive.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./chapter_and_verse.db"


class Settings(DatabaseSettings):
    # Only the API needs the key. Migrations read DatabaseSettings.
    claude_api_token: SecretStr
    claude_model: str = "claude-haiku-4-5"
    claude_timeout_seconds: float = 60.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
