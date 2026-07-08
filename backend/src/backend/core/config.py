from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the backend, sourced from env vars / .env."""

    model_config = SettingsConfigDict(
        env_prefix="BACKEND_",
        env_file=".env",
        extra="ignore",
    )

    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:5173"]
    database_url: str = "postgresql+asyncpg://price_discovery:price_discovery@localhost:5432/price_discovery"
    refresh_interval_minutes: int = 30
    default_entsoe_area: str = "10Y1001A1001A82H"  # DE-LU
    default_elexon_provider: str = "APX"


@lru_cache
def get_settings() -> Settings:
    return Settings()
