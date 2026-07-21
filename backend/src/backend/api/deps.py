from esios_retriever import EsiosClient
from fastapi import Request

from backend.services.indicator_discovery import IndicatorDiscoveryService
from backend.services.outage_discovery import OutageDiscoveryService
from backend.services.price_discovery import PriceDiscoveryService


def get_price_discovery_service(request: Request) -> PriceDiscoveryService:
    return request.app.state.price_discovery_service


def get_indicator_discovery_service(request: Request) -> IndicatorDiscoveryService:
    return request.app.state.indicator_discovery_service


def get_outage_discovery_service(request: Request) -> OutageDiscoveryService:
    return request.app.state.outage_discovery_service


def get_esios_client(request: Request) -> EsiosClient:
    return request.app.state.esios_client
