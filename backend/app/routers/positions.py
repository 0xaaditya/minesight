import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.geo import haversine_meters
from app.models import Position, Vehicle
from app.schemas import PositionOut, VehicleStatsOut
from app.time_utils import ist_day_bounds, ist_range_bounds

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


@router.get("/{vehicle_id}/stats", response_model=VehicleStatsOut)
def vehicle_stats(
    vehicle_id: uuid.UUID,
    date_: Optional[date] = Query(default=None, alias="date"),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Live "Distance" tile for the vehicle detail page — every vehicle type, not just
    haul-cycle ones (an excavator or bowser has no Trip rows to sum, but it still moves).
    Same one-or-the-other date convention as /trips' _apply_started_at_filter. Primary
    source: delta of Traccar's own cumulative odometer, same as
    trip_engine._path_distance_m (CLAUDE.md: don't rebuild what Traccar provides);
    falls back to a haversine breadcrumb sum if the odometer is missing or reset."""
    if not db.get(Vehicle, vehicle_id):
        raise HTTPException(status_code=404, detail="vehicle not found")

    stmt = select(Position.latitude, Position.longitude, Position.total_distance_m).where(
        Position.vehicle_id == vehicle_id
    )
    if date_ is not None:
        start, end = ist_day_bounds(date_)
        stmt = stmt.where(Position.event_time >= start, Position.event_time < end)
    elif start_date is not None and end_date is not None:
        start, end = ist_range_bounds(start_date, end_date)
        stmt = stmt.where(Position.event_time >= start, Position.event_time < end)
    rows = db.execute(stmt.order_by(Position.event_time.asc())).all()

    if len(rows) < 2:
        return VehicleStatsOut(distance_m=None)
    first_odo, last_odo = rows[0][2], rows[-1][2]
    if first_odo is not None and last_odo is not None and last_odo >= first_odo:
        return VehicleStatsOut(distance_m=last_odo - first_odo)
    distance_m = sum(
        haversine_meters(rows[i - 1][0], rows[i - 1][1], rows[i][0], rows[i][1]) for i in range(1, len(rows))
    )
    return VehicleStatsOut(distance_m=distance_m)


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
