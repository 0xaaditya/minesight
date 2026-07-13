import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Trip, Vehicle
from app.schemas import TripOut

router = APIRouter(prefix="/vehicles", tags=["trips"])

IST_OFFSET = timedelta(hours=5, minutes=30)


def ist_day_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC times stored, IST displayed (CLAUDE.md convention) — UTC midnight is 5:30am IST,
    right in the middle of a mining shift, so any 'today' rollup must use IST day
    boundaries or it'll split a live shift across two report-days."""
    start_ist_as_utc = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - IST_OFFSET
    return start_ist_as_utc, start_ist_as_utc + timedelta(days=1)


@router.get("/{vehicle_id}/trips", response_model=list[TripOut])
def list_trips(
    vehicle_id: uuid.UUID,
    date_: Optional[date] = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
):
    if not db.get(Vehicle, vehicle_id):
        raise HTTPException(status_code=404, detail="vehicle not found")

    stmt = select(Trip).where(Trip.vehicle_id == vehicle_id)
    if date_ is not None:
        start, end = ist_day_bounds(date_)
        stmt = stmt.where(Trip.started_at >= start, Trip.started_at < end)
    stmt = stmt.order_by(Trip.started_at.asc())
    return db.scalars(stmt).all()
