# traccar_client.py — thin client for Traccar's management REST API. Only used for
# device registration today (so the owner never has to open Traccar's own UI); position
# data still flows the other way, Traccar → our webhook. Deliberately never raises:
# vehicle registration in OUR registry must succeed even when Traccar is down, so every
# outcome is reported as a (status, detail) tuple the router forwards to the dashboard.
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5.0

# Statuses surfaced on the POST /vehicles response (schemas.VehicleOut.traccar_status).
STATUS_CREATED = "created"
STATUS_EXISTS = "exists"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


def create_device(name: str, unique_id: str) -> tuple[str, str]:
    """Create a device in Traccar (name = our asset ID, uniqueId = what the tracker
    sends in its OsmAnd `id=` param). Sync httpx is fine: our routers are sync `def`
    endpoints running in FastAPI's threadpool."""
    if not (settings.traccar_api_url and settings.traccar_api_user and settings.traccar_api_password):
        return STATUS_SKIPPED, "Traccar API not configured (TRACCAR_API_URL/USER/PASSWORD)"

    url = settings.traccar_api_url.rstrip("/") + "/devices"
    try:
        response = httpx.post(
            url,
            json={"name": name, "uniqueId": unique_id},
            auth=(settings.traccar_api_user, settings.traccar_api_password),
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        logger.warning("Traccar device creation failed for %s: %s", unique_id, exc)
        return STATUS_FAILED, f"Traccar unreachable at {settings.traccar_api_url}: {type(exc).__name__}"

    if response.is_success:
        return STATUS_CREATED, f"Device {unique_id} created in Traccar"
    if response.status_code == 401:
        return STATUS_FAILED, "Traccar rejected the credentials — check TRACCAR_API_USER/PASSWORD"
    # Traccar answers 400 with a SQL duplicate-key message when the uniqueId is taken —
    # benign for us (the device already exists, e.g. it auto-registered on first ping).
    if response.status_code == 400 and "unique" in response.text.lower():
        return STATUS_EXISTS, f"Device {unique_id} already exists in Traccar"

    logger.warning(
        "Traccar device creation for %s returned %s: %s", unique_id, response.status_code, response.text[:200]
    )
    return STATUS_FAILED, f"Traccar returned {response.status_code}"
