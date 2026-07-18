# bootstrap.py — idempotent provisioning via the REAL backend REST API only. Never
# touches Postgres or Traccar directly: POST /vehicles already side-registers the
# Traccar device (backend/app/traccar_client.py, called from
# backend/app/routers/vehicles.py), so re-using it here is what actually proves the
# simulator through the same path production hardware onboarding will use.
import logging

import httpx

from simulator.identity import VehicleSpec
from simulator.layout import SiteLayout

logger = logging.getLogger(__name__)


class Fixtures:
    def __init__(self, vehicle_ids: dict[str, str], zone_ids: dict[str, str]):
        self.vehicle_ids = vehicle_ids  # asset_id -> vehicle uuid (str)
        self.zone_ids = zone_ids  # zone name -> zone uuid (str)


def bootstrap(backend_api_url: str, roster: list[VehicleSpec], layout: SiteLayout) -> Fixtures:
    with httpx.Client(base_url=backend_api_url, timeout=10.0) as client:
        existing_vehicles = {v["asset_id"]: v["id"] for v in client.get("/vehicles", params={"include_inactive": True}).raise_for_status().json()}
        vehicle_ids: dict[str, str] = {}
        for spec in roster:
            if spec.asset_id in existing_vehicles:
                vehicle_ids[spec.asset_id] = existing_vehicles[spec.asset_id]
                logger.info("vehicle %s already registered, reusing", spec.asset_id)
                continue
            resp = client.post(
                "/vehicles",
                json={
                    "asset_id": spec.asset_id,
                    "vehicle_type": spec.vehicle_type,
                    "traccar_unique_id": spec.traccar_unique_id,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            vehicle_ids[spec.asset_id] = body["id"]
            logger.info(
                "created vehicle %s (traccar_status=%s)", spec.asset_id, body.get("traccar_status")
            )

        existing_zones = {z["name"]: z["id"] for z in client.get("/zones").raise_for_status().json()}
        zone_ids: dict[str, str] = {}
        for zspec in layout.zones:
            if zspec.name in existing_zones:
                zone_ids[zspec.name] = existing_zones[zspec.name]
                logger.info("zone %s already exists, reusing", zspec.name)
                continue
            resp = client.post(
                "/zones",
                json={
                    "name": zspec.name,
                    "zone_type": zspec.zone_type,
                    "geometry": zspec.geometry,
                    "speed_limit_kmph": zspec.speed_limit_kmph,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            zone_ids[zspec.name] = body["id"]
            logger.info("created zone %s", zspec.name)

    return Fixtures(vehicle_ids=vehicle_ids, zone_ids=zone_ids)
