from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Package-relative, not cwd-relative — see the identical comment in
# entsoe_retriever/config.py; this makes the package find its own .env
# regardless of who imports it or from where (e.g. embedded in `backend`).
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


class EsiosSettings(BaseSettings):
    """Runtime configuration for the ESIOS client, sourced from env vars / .env."""

    model_config = SettingsConfigDict(
        env_prefix="ESIOS_",
        env_file=_PACKAGE_ROOT / ".env",
        extra="ignore",
    )

    api_token: str | None = Field(
        default=None,
        description="Personal token issued by REE (request via consultasios@ree.es).",
    )
    base_url: str = "https://api.esios.ree.es"
    request_timeout_seconds: float = 30.0
    max_retries: int = 3
    cache_dir: str = "data/cache"
    cache_ttl_seconds: int = 3600


@lru_cache
def get_settings() -> EsiosSettings:
    return EsiosSettings()
