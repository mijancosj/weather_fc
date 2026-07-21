from contextlib import asynccontextmanager

from elexon_retriever import ElexonClient
from entsoe_retriever import EntsoeClient
from esios_retriever import EsiosClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import health, indicators, internal, outages, prices, sources
from backend.core.config import get_settings
from backend.core.logging import configure_logging
from backend.core.scheduler import start_scheduler
from backend.db.session import create_engine, create_session_factory
from backend.services.indicator_discovery import IndicatorDiscoveryService
from backend.services.outage_discovery import OutageDiscoveryService
from backend.services.price_discovery import PriceDiscoveryService
from backend.services.storage import IndicatorRepository, OutageRepository, PriceRepository


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.environment)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    price_repository = PriceRepository(session_factory)
    indicator_repository = IndicatorRepository(session_factory)
    outage_repository = OutageRepository(session_factory)

    entsoe_client = EntsoeClient()
    elexon_client = ElexonClient()
    esios_client = EsiosClient()
    price_service = PriceDiscoveryService(entsoe_client, elexon_client, esios_client, price_repository)
    indicator_service = IndicatorDiscoveryService(esios_client, entsoe_client, indicator_repository)
    outage_service = OutageDiscoveryService(entsoe_client, outage_repository)

    app.state.price_discovery_service = price_service
    app.state.indicator_discovery_service = indicator_service
    app.state.outage_discovery_service = outage_service
    app.state.esios_client = esios_client
    scheduler = start_scheduler(settings, price_service, indicator_service, outage_service)

    yield

    scheduler.shutdown(wait=False)
    await entsoe_client.aclose()
    await elexon_client.aclose()
    await esios_client.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Price Discovery Backend", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(prices.router)
    app.include_router(sources.router)
    app.include_router(indicators.router)
    app.include_router(outages.router)
    app.include_router(internal.router)

    return app


app = create_app()
