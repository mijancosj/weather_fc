from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from entsoe_retriever import AreaCode, EntsoeClient, OutageEvent
from entsoe_retriever.exceptions import EntsoeApiError

from backend.services.storage import OutageRepository

log = structlog.get_logger()

# ENTSO-E caps outage responses at 200 "instances" per request (confirmed
# live: FR alone returned a 400 "exceeds the allowed maximum (200)" for the
# default 97-day window, ES/PT didn't). Outage density varies unpredictably
# by country and time, so rather than guess a fixed chunk size, split the
# window in half and retry whenever this specific error is hit.
_TOO_MANY_INSTANCES_MARKER = "exceeds the allowed maximum"
_MIN_SPLIT_WINDOW = timedelta(days=1)


async def _fetch_generation_outages_adaptive(
    client: EntsoeClient, area: AreaCode, start: datetime, end: datetime
) -> list[OutageEvent]:
    try:
        return await client.get_generation_outages(area, start, end)
    except EntsoeApiError as exc:
        if _TOO_MANY_INSTANCES_MARKER not in exc.body or end - start <= _MIN_SPLIT_WINDOW:
            raise
        midpoint = start + (end - start) / 2
        first_half = await _fetch_generation_outages_adaptive(client, area, start, midpoint)
        second_half = await _fetch_generation_outages_adaptive(client, area, midpoint, end)
        return first_half + second_half


async def _fetch_transmission_outages_adaptive(
    client: EntsoeClient, area_in: AreaCode, area_out: AreaCode, start: datetime, end: datetime
) -> list[OutageEvent]:
    try:
        return await client.get_transmission_outages(area_in, area_out, start, end)
    except EntsoeApiError as exc:
        if _TOO_MANY_INSTANCES_MARKER not in exc.body or end - start <= _MIN_SPLIT_WINDOW:
            raise
        midpoint = start + (end - start) / 2
        first_half = await _fetch_transmission_outages_adaptive(
            client, area_in, area_out, start, midpoint
        )
        second_half = await _fetch_transmission_outages_adaptive(
            client, area_in, area_out, midpoint, end
        )
        return first_half + second_half


class OutageDiscoveryService:
    """Refreshes ENTSO-E outage notifications (generation-unit and
    transmission-asset unavailability) into Postgres.

    Outages are often the single biggest short-term price mover and easy to
    miss if you're not tracking them — this pulls both planned maintenance
    and forced unavailability for tracked bidding zones and interconnector
    borders on every refresh. A wide window (7 days back, 90 days ahead) is
    used deliberately: outages are announced well in advance and can run for
    months, unlike prices/generation/load which only need a day or two.
    """

    def __init__(self, entsoe_client: EntsoeClient, repository: OutageRepository) -> None:
        self._entsoe = entsoe_client
        self._repository = repository

    async def refresh_generation_outages(self, areas: list[AreaCode]) -> None:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=7)
        window_end = now + timedelta(days=90)
        rows: list[dict] = []

        for area in areas:
            try:
                events = await _fetch_generation_outages_adaptive(
                    self._entsoe, area, window_start, window_end
                )
            except Exception:
                log.exception("entsoe.generation_outages.refresh.failed", area=area.name)
                continue
            rows.extend(_row_from_event(event) for event in events)

        if rows:
            await self._repository.upsert_outages(rows)

    async def refresh_transmission_outages(
        self, border_pairs: list[tuple[AreaCode, AreaCode]]
    ) -> None:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=7)
        window_end = now + timedelta(days=90)
        rows: list[dict] = []

        for area_in, area_out in border_pairs:
            try:
                events = await _fetch_transmission_outages_adaptive(
                    self._entsoe, area_in, area_out, window_start, window_end
                )
            except Exception:
                log.exception(
                    "entsoe.transmission_outages.refresh.failed",
                    area_in=area_in.name,
                    area_out=area_out.name,
                )
                continue
            rows.extend(_row_from_event(event) for event in events)

        if rows:
            await self._repository.upsert_outages(rows)

    async def latest(
        self,
        resource_type: str | None = None,
        area: str | None = None,
        active_only: bool = False,
    ) -> list[dict]:
        active_at = datetime.now(timezone.utc) if active_only else None
        return await self._repository.query(
            resource_type=resource_type, area=area, active_at=active_at
        )


def _row_from_event(event: OutageEvent) -> dict:
    capacities = [point.available_capacity_mw for point in event.points]
    return {
        "event_id": event.event_id,
        "revision_number": event.revision_number,
        "resource_type": event.resource_type,
        "business_type": event.business_type,
        "reason_code": event.reason_code,
        "area": event.area,
        "in_area": event.in_area,
        "out_area": event.out_area,
        "unit_id": event.unit_id,
        "unit_name": event.unit_name,
        "location_name": event.location_name,
        "psr_type": event.psr_type,
        "nominal_capacity_mw": event.nominal_capacity_mw,
        "min_available_capacity_mw": min(capacities) if capacities else None,
        "max_available_capacity_mw": max(capacities) if capacities else None,
        "period_start": event.period_start,
        "period_end": event.period_end,
    }
