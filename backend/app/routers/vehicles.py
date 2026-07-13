import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import traccar_client, trip_engine
from app.database import get_db
from app.models import Organization, Position, Vehicle, VehicleTripState, VehicleType
from app.schemas import PositionOut, VehicleCreate, VehicleOut, derive_vehicle_type

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.post("", response_model=VehicleOut, status_code=201)
def create_vehicle(payload: VehicleCreate, db: Session = Depends(get_db)):
    vehicle_type = payload.vehicle_type or derive_vehicle_type(payload.asset_id)
    if vehicle_type is None:
        raise HTTPException(
            status_code=422,
            detail="vehicle_type not given and asset_id doesn't match a known prefix "
            "(S-, EX-, L-, BB-, K-, CSM-)",
        )

    org = db.scalar(select(Organization).limit(1))
    if org is None:
        raise HTTPException(status_code=500, detail="No organization seeded — run migrations")

    if db.scalar(select(Vehicle).where(Vehicle.asset_id == payload.asset_id)):
        raise HTTPException(status_code=409, detail=f"asset_id {payload.asset_id} already registered")

    traccar_unique_id = payload.traccar_unique_id or payload.asset_id
    if db.scalar(select(Vehicle).where(Vehicle.traccar_unique_id == traccar_unique_id)):
        raise HTTPException(
            status_code=409,
            detail=f"device ID {traccar_unique_id} is already linked to another vehicle",
        )

    vehicle = Vehicle(
        org_id=org.id,
        asset_id=payload.asset_id,
        vehicle_type=vehicle_type,
        traccar_unique_id=traccar_unique_id,
        registration_number=payload.registration_number,
        manufacturer=payload.manufacturer,
        capacity_tonnes=payload.capacity_tonnes,
    )
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)

    # After commit on purpose: our registry is authoritative, and Traccar being down
    # must never block fleet onboarding (the webhook simply won't match this device
    # until it exists in Traccar). Outcome is reported, not raised.
    traccar_status, traccar_detail = traccar_client.create_device(
        name=vehicle.asset_id, unique_id=vehicle.traccar_unique_id
    )
    out = _with_latest_position(vehicle, db)
    out.traccar_status = traccar_status
    out.traccar_detail = traccar_detail
    return out


@router.get("", response_model=list[VehicleOut])
def list_vehicles(db: Session = Depends(get_db)):
    vehicles = db.scalars(select(Vehicle)).all()
    return [_with_latest_position(v, db) for v in vehicles]


@router.get("/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(vehicle_id: uuid.UUID, db: Session = Depends(get_db)):
    """Single-vehicle read for the deep-linkable detail page (/vehicles/:id)."""
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="vehicle not found")
    return _with_latest_position(vehicle, db)


def _with_latest_position(vehicle: Vehicle, db: Session) -> VehicleOut:
    latest = db.scalar(
        select(Position)
        .where(Position.vehicle_id == vehicle.id)
        .order_by(Position.event_time.desc())
        .limit(1)
    )
    trip_state = db.scalar(
        select(VehicleTripState).where(VehicleTripState.vehicle_id == vehicle.id)
    )
    now = datetime.now(timezone.utc)
    is_paired = (
        trip_engine.excavator_is_paired(db, vehicle.id, now)
        if vehicle.vehicle_type == VehicleType.EXCAVATOR
        else False
    )
    out = VehicleOut.model_validate(vehicle)
    out.latest_position = PositionOut.model_validate(latest) if latest else None
    out.trip_status = trip_state.trip_status if trip_state else None
    out.status = trip_engine.compute_vehicle_status(latest, trip_state, now, is_paired)
    return out
