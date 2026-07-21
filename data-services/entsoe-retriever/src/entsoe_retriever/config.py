from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Package-relative, not cwd-relative: pydantic-settings resolves a plain
# ".env" against the current working directory, which is wrong here — when
# this package runs embedded in `backend` (whose own cwd is backend/), a
# relative path would silently miss data-services/entsoe-retriever/.env and
# fall back to real env vars / backend's own .env instead. This makes the
# package find its own .env regardless of who imports it or from where.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


class EntsoeSettings(BaseSettings):
    """Runtime configuration for the ENTSO-E client, sourced from env vars / .env."""

    model_config = SettingsConfigDict(
        env_prefix="ENTSOE_",
        env_file=_PACKAGE_ROOT / ".env",
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
