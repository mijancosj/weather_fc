from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EntsoeSettings(BaseSettings):
    """Runtime configuration for the ENTSO-E client, sourced from env vars / .env."""

    model_config = SettingsConfigDict(
        env_prefix="ENTSOE_",
        env_file=".env",
        extra="ignore",
    )

    api_token: str | None = Field(
        default=None,
        description="Security token issued by the ENTSO-E Transparency Platform.",
    )
    base_url: str = "https://web-api.tp.entsoe.eu/api"
    request_timeout_seconds: float = 30.0
    max_retries: int = 3
    cache_dir: str = "data/cache"
    cache_ttl_seconds: int = 3600


@lru_cache
def get_settings() -> EntsoeSettings:
    return EntsoeSettings()
