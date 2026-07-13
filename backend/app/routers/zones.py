import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Organization, Zone, ZoneAuditLog, ZoneAuditAction
from app.schemas import ZoneCreate, ZoneOut

router = APIRouter(prefix="/zones", tags=["zones"])


def _snapshot(zone: Zone) -> dict:
    return {
        "name": zone.name,
        "zone_type": zone.zone_type.value,
        "geometry": zone.geometry,
    }


@router.post("", response_model=ZoneOut, status_code=201)
def create_zone(payload: ZoneCreate, db: Session = Depends(get_db)):
    org = db.scalar(select(Organization).limit(1))
    if org is None:
        raise HTTPException(status_code=500, detail="No organization seeded — run migrations")

    zone = Zone(
        zone_key=uuid.uuid4(),
        org_id=org.id,
        name=payload.name,
        zone_type=payload.zone_type,
        geometry=payload.geometry,
    )
    db.add(zone)
    db.flush()

    db.add(
        ZoneAuditLog(
            zone_key=zone.zone_key,
            action=ZoneAuditAction.CREATE,
            old_value=None,
            new_value=_snapshot(zone),
        )
    )
    db.commit()
    db.refresh(zone)
    return zone


@router.put("/{zone_key}", response_model=ZoneOut)
def update_zone(zone_key: uuid.UUID, payload: ZoneCreate, db: Session = Depends(get_db)):
    current = db.scalar(
        select(Zone).where(Zone.zone_key == zone_key, Zone.valid_to.is_(None))
    )
    if current is None:
        raise HTTPException(status_code=404, detail="zone not found or has no current version")

    old_snapshot = _snapshot(current)
    now = datetime.now(timezone.utc)
    current.valid_to = now

    new_version = Zone(
        zone_key=zone_key,
        org_id=current.org_id,
        name=payload.name,
        zone_type=payload.zone_type,
        geometry=payload.geometry,
        valid_from=now,
    )
    db.add(new_version)
    db.flush()

    db.add(
        ZoneAuditLog(
            zone_key=zone_key,
            action=ZoneAuditAction.UPDATE,
            old_value=old_snapshot,
            new_value=_snapshot(new_version),
        )
    )
    db.commit()
    db.refresh(new_version)
    return new_version


@router.delete("/{zone_key}", status_code=204)
def delete_zone(zone_key: uuid.UUID, db: Session = Depends(get_db)):
    current = db.scalar(
        select(Zone).where(Zone.zone_key == zone_key, Zone.valid_to.is_(None))
    )
    if current is None:
        raise HTTPException(status_code=404, detail="zone not found or has no current version")

    old_snapshot = _snapshot(current)
    current.valid_to = datetime.now(timezone.utc)

    db.add(
        ZoneAuditLog(
            zone_key=zone_key,
            action=ZoneAuditAction.CLOSE,
            old_value=old_snapshot,
            new_value=None,
        )
    )
    db.commit()


@router.get("", response_model=list[ZoneOut])
def list_zones(as_of: Optional[datetime] = Query(default=None), db: Session = Depends(get_db)):
    if as_of is None:
        stmt = select(Zone).where(Zone.valid_to.is_(None))
    else:
        stmt = select(Zone).where(
            Zone.valid_from <= as_of, (Zone.valid_to.is_(None)) | (Zone.valid_to > as_of)
        )
    return db.scalars(stmt).all()
