import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Position, Vehicle
from app.schemas import PositionOut
from app.time_utils import ist_day_bounds

router = APIRouter(prefix="/vehicles", tags=["positions"])


@router.get("/{vehicle_id}/positions", response_model=list[PositionOut])
def list_positions(
    vehicle_id: uuid.UUID,
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    date_: Optional[date] = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
):
    """`date` (IST day, for route replay) takes precedence over `since`/`until` — same
    one-or-the-other convention as /trips. `until` bounds a `since` query so a single
    trip's breadcrumb (started_at → completed_at) can be fetched without pulling the
    rest of the day. Positions never delete inside the 90-day retention window
    (CLAUDE.md), so an old date always has a full breadcrumb to replay."""
    if not db.get(Vehicle, vehicle_id):
        raise HTTPException(status_code=404, detail="vehicle not found")

    stmt = select(Position).where(Position.vehicle_id == vehicle_id)
    if date_ is not None:
        start, end = ist_day_bounds(date_)
        stmt = stmt.where(Position.event_time >= start, Position.event_time < end)
    else:
        if since is not None:
            stmt = stmt.where(Position.event_time >= since)
        if until is not None:
            stmt = stmt.where(Position.event_time <= until)
    stmt = stmt.order_by(Position.event_time.asc())
    return db.scalars(stmt).all()


@router.get("/{vehicle_id}/positions/latest", response_model=PositionOut)
def latest_position(vehicle_id: uuid.UUID, db: Session = Depends(get_db)):
    if not db.get(Vehicle, vehicle_id):
        raise HTTPException(status_code=404, detail="vehicle not found")

    position = db.scalar(
        select(Position)
        .where(Position.vehicle_id == vehicle_id)
        .order_by(Position.event_time.desc())
        .limit(1)
    )
    if position is None:
        raise HTTPException(status_code=404, detail="no positions yet")
    return position
