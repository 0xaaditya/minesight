import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, Vehicle, Zone
from app.schemas import EventOut
from app.time_utils import ist_day_bounds

router = APIRouter(prefix="/events", tags=["events"])


def _resolve_names(db: Session, events: list[Event]) -> list[EventOut]:
    vehicle_ids = {e.vehicle_id for e in events}
    zone_ids = {e.zone_id for e in events if e.zone_id}
    asset_ids = (
        dict(db.execute(select(Vehicle.id, Vehicle.asset_id).where(Vehicle.id.in_(vehicle_ids))).all())
        if vehicle_ids
        else {}
    )
    zone_names = (
        dict(db.execute(select(Zone.id, Zone.name).where(Zone.id.in_(zone_ids))).all()) if zone_ids else {}
    )
    out = []
    for e in events:
        row = EventOut.model_validate(e)
        row.vehicle_asset_id = asset_ids.get(e.vehicle_id)
        if e.zone_id:
            row.zone_name = zone_names.get(e.zone_id)
        out.append(row)
    return out


@router.get("", response_model=list[EventOut])
def list_events(
    limit: int = Query(default=50, le=200),
    date_: Optional[date] = Query(default=None, alias="date"),
    vehicle_id: Optional[uuid.UUID] = Query(default=None),
    unacknowledged_only: bool = Query(default=False),
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    stmt = select(Event)
    if date_ is not None:
        start, end = ist_day_bounds(date_)
        stmt = stmt.where(Event.event_time >= start, Event.event_time < end)
    if vehicle_id is not None:
        stmt = stmt.where(Event.vehicle_id == vehicle_id)
    elif not include_inactive:
        # Deactivated vehicles (retired hardware, simulator teardown) shouldn't clutter
        # the live feed or the unacknowledged badge — same default as GET /vehicles.
        # Explicit vehicle_id lookups still return everything, mirroring GET /vehicles/{id}.
        stmt = stmt.where(
            Event.vehicle_id.in_(select(Vehicle.id).where(Vehicle.deactivated_at.is_(None)))
        )
    if unacknowledged_only:
        stmt = stmt.where(Event.acknowledged_at.is_(None))
    stmt = stmt.order_by(Event.event_time.desc()).limit(limit)
    events = db.scalars(stmt).all()
    return _resolve_names(db, events)


@router.post("/{event_id}/ack", response_model=EventOut)
def acknowledge_event(event_id: uuid.UUID, db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    if event.acknowledged_at is None:
        event.acknowledged_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(event)
    return _resolve_names(db, [event])[0]
