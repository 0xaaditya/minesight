# osmand_client.py — sends the exact OsmAnd query string real firmware builds
# (firmware/sketch_jul10a/transport.h buildUrl(), verified directly), plus the
# fuel/driver/ignition/batt fields CLAUDE.md's wire spec names but firmware doesn't
# send yet (its own comment: "omitted until those sensors land later in Phase 1").
# These are forward-compat only — backend/app/routers/webhook.py never reads them
# (only hdop/sat/totalDistance out of attributes), so nothing here is ever scored.
from dataclasses import dataclass

import httpx


@dataclass
class OsmAndTick:
    traccar_unique_id: str
    epoch_utc: int
    lat: float
    lon: float
    speed_knots: float
    course: float
    hdop: float
    sat: int
    fuel_level_pct: float
    driver_id: str
    ignition: bool
    batt_voltage: float


@dataclass
class SendResult:
    ok: bool
    status_code: int | None
    error: str | None


def build_url(base_url: str, tick: OsmAndTick, device_token: str = "SIM-TOKEN") -> str:
    return (
        f"{base_url}/"
        f"?id={tick.traccar_unique_id}"
        f"&timestamp={tick.epoch_utc}"
        f"&lat={tick.lat:.6f}"
        f"&lon={tick.lon:.6f}"
        f"&speed={tick.speed_knots:.1f}"
        f"&bearing={tick.course:.1f}"
        f"&hdop={tick.hdop:.2f}"
        f"&sat={tick.sat}"
        f"&devicetoken={device_token}"
        f"&fuel={tick.fuel_level_pct:.1f}"
        f"&driver={tick.driver_id}"
        f"&ignition={'true' if tick.ignition else 'false'}"
        f"&batt={tick.batt_voltage:.2f}"
    )


class OsmAndClient:
    """Never raises on transport failure — mirrors traccar_client.py's "never block"
    philosophy: a dropped send is exactly what a gps_dropout/wifi_gap scenario wants to
    simulate anyway, so the caller (vehicle_agent) decides what a failure means, not this
    client."""

    def __init__(self, base_url: str, timeout_s: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def send(self, tick: OsmAndTick) -> SendResult:
        url = build_url(self.base_url, tick)
        try:
            resp = await self._client.get(url)
            return SendResult(ok=resp.status_code == 200, status_code=resp.status_code, error=None)
        except httpx.HTTPError as e:
            return SendResult(ok=False, status_code=None, error=str(e))

    async def aclose(self) -> None:
        await self._client.aclose()
