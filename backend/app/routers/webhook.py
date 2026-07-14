import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import event_engine, trip_engine
from app.database import get_db
from app.models import Position, Vehicle
from app.schemas import TraccarForwardPayload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post("/traccar", status_code=201)
def traccar_forward(payload: TraccarForwardPayload, db: Session = Depends(get_db)):
    unique_id = payload.device.uniqueId
    vehicle = db.scalar(select(Vehicle).where(Vehicle.traccar_unique_id == unique_id))
    if vehicle is None:
        # Mirrors Traccar's own "unknown device" rejection: the registry stays
        # authoritative in one place (our DB), no orphan position rows.
        logger.warning("Unknown device forwarded from Traccar: %s", unique_id)
        raise HTTPException(status_code=404, detail=f"vehicle {unique_id} not registered")

    pos = payload.position
    position = Position(
        vehicle_id=vehicle.id,
        org_id=vehicle.org_id,
        event_time=pos.fixTime,
        received_at=pos.serverTime,
        latitude=pos.latitude,
        longitude=pos.longitude,
        speed_knots=pos.speed,
        course=pos.course,
        hdop=pos.attributes.get("hdop"),
        satellites=pos.attributes.get("sat"),
        total_distance_m=pos.attributes.get("totalDistance"),
        raw=payload.model_dump(mode="json"),
    )
    db.add(position)
    db.commit()

    try:
        trip_engine.process_position(db, position.id)
    except Exception:
        # A transient engine bug shouldn't make Traccar think delivery failed and
        # retry/backlog — the position is already safely stored above.
        db.rollback()
        logger.exception("trip_engine.process_position failed for position %s", position.id)

    # Independent try/except: event detection must run for every vehicle type (trip_engine
    # skips non-haul types), and a failure in one engine must never starve the other. Runs
    # after trip_engine so BREAKDOWN detection sees this tick's fresh trip_status.
    try:
        event_engine.process_position_events(db, position.id)
    except Exception:
        db.rollback()
        logger.exception("event_engine.process_position_events failed for position %s", position.id)

    return {"status": "ok"}
