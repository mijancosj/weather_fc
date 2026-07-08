from contextlib import asynccontextmanager

from elexon_retriever import ElexonClient
from entsoe_retriever import EntsoeClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import health, prices, sources
from backend.core.config import get_settings
from backend.core.logging import configure_logging
from backend.core.scheduler import start_scheduler
from backend.db.session import create_engine, create_session_factory
from backend.services.price_discovery import PriceDiscoveryService
from backend.services.storage import PriceRepository


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.environment)

    engine = create_engine(settings)
    repository = PriceRepository(create_session_factory(engine))

    entsoe_client = EntsoeClient()
    elexon_client = ElexonClient()
    service = PriceDiscoveryService(entsoe_client, elexon_client, repository)

    app.state.price_discovery_service = service
    scheduler = start_scheduler(settings, service)

    yield

    scheduler.shutdown(wait=False)
    await entsoe_client.aclose()
    await elexon_client.aclose()
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

    return app


app = create_app()
