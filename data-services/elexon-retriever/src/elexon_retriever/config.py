from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ElexonSettings(BaseSettings):
    """Runtime configuration for the Elexon Insights Solution client."""

    model_config = SettingsConfigDict(
        env_prefix="ELEXON_",
        env_file=".env",
        extra="ignore",
    )

    api_key: str | None = Field(
        default=None,
        description="Optional bearer token for higher-rate-limit Elexon endpoints.",
    )
    base_url: str = "https://data.elexon.co.uk/bmrs/api/v1"
    request_timeout_seconds: float = 30.0
    max_retries: int = 3
    cache_dir: str = "data/cache"
    cache_ttl_seconds: int = 3600


@lru_cache
def get_settings() -> ElexonSettings:
    return ElexonSettings()
