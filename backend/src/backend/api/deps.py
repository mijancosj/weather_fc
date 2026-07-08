from fastapi import Request

from backend.services.price_discovery import PriceDiscoveryService


def get_price_discovery_service(request: Request) -> PriceDiscoveryService:
    return request.app.state.price_discovery_service
