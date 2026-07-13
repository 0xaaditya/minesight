import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Trip, Vehicle
from app.schemas import TripOut
from app.time_utils import ist_day_bounds

router = APIRouter(prefix="/vehicles", tags=["trips"])


def _asset_id_map(db: Session, vehicle_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not vehicle_ids:
        return {}
    rows = db.execute(select(Vehicle.id, Vehicle.asset_id).where(Vehicle.id.in_(vehicle_ids))).all()
    return {vid: asset_id for vid, asset_id in rows}


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
    trips = db.scalars(stmt).all()

    excavator_names = _asset_id_map(
        db, {t.load_excavator_vehicle_id for t in trips if t.load_excavator_vehicle_id}
    )
    out = []
    for t in trips:
        row = TripOut.model_validate(t)
        if t.load_excavator_vehicle_id:
            row.load_excavator_asset_id = excavator_names.get(t.load_excavator_vehicle_id)
        out.append(row)
    return out


@router.get("/{vehicle_id}/loads", response_model=list[TripOut])
def list_loads(
    vehicle_id: uuid.UUID,
    date_: Optional[date] = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
):
    """The excavator-facing view of the same trips table: every trip THIS vehicle loaded
    (load_excavator_vehicle_id == it). Trips make no sense on an excavator card — what an
    owner wants there is 'how many trucks did it fill today' — so the dashboard queries
    this instead of /trips for excavators."""
    if not db.get(Vehicle, vehicle_id):
        raise HTTPException(status_code=404, detail="vehicle not found")

    stmt = select(Trip).where(Trip.load_excavator_vehicle_id == vehicle_id)
    if date_ is not None:
        start, end = ist_day_bounds(date_)
        stmt = stmt.where(Trip.started_at >= start, Trip.started_at < end)
    stmt = stmt.order_by(Trip.started_at.asc())
    trips = db.scalars(stmt).all()

    truck_names = _asset_id_map(db, {t.vehicle_id for t in trips})
    out = []
    for t in trips:
        row = TripOut.model_validate(t)
        row.vehicle_asset_id = truck_names.get(t.vehicle_id)
        out.append(row)
    return out
