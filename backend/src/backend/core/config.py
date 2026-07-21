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
    # GB deliberately excluded: confirmed against the live API that ENTSO-E
    # has no day-ahead price or generation data for GB (post-Brexit market
    # decoupling) — Elexon is GB's only real source here, wired separately.
    entsoe_areas: list[str] = [
        "10YFR-RTE------C",  # FR
        "10YES-REE------0",  # ES
        "10YPT-REN------W",  # PT
    ]
    default_elexon_provider: str = "APX"
    # Which ESIOS indicators (beyond the day-ahead price, which is always
    # refreshed) to pull into indicator_observations. Empty by default —
    # use EsiosClient.list_indicators() to find IDs worth tracking, then add
    # them here, e.g. BACKEND_ESIOS_INDICATOR_IDS=[1293,10035]
    esios_indicator_ids: list[int] = []
    # Interconnector borders to track for transmission outages, as
    # [in_Domain, out_Domain] EIC pairs — confirmed live for ES-FR and ES-PT.
    # Spain-Morocco is deliberately not here: Morocco isn't an ENTSO-E member,
    # so this transparency-platform endpoint has no data for that border.
    entsoe_border_pairs: list[list[str]] = [
        ["10YES-REE------0", "10YFR-RTE------C"],  # ES-FR
        ["10YES-REE------0", "10YPT-REN------W"],  # ES-PT
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
