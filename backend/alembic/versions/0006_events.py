"""events/alerts pipeline: events table, vehicle_event_state, zone speed limits

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-14

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

EVENT_TYPE_ENUM = sa.Enum("night_movement", "boundary_exit", "zone_overspeed", "breakdown", name="eventtype")
EVENT_SEVERITY_ENUM = sa.Enum("critical", "warning", name="eventseverity")


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("vehicle_id", UUID(as_uuid=True), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column("event_type", EVENT_TYPE_ENUM, nullable=False),
        sa.Column("severity", EVENT_SEVERITY_ENUM, nullable=False),
        # event_time = episode start (from the triggering position's event_time);
        # detected_at = wall-clock time the row was written. Same "process by event
        # timestamp, not arrival time" discipline as Position (CLAUDE.md).
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("zone_id", UUID(as_uuid=True), sa.ForeignKey("zones.id"), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column("delayed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        # No User model yet (auth deferred) — same convention as ZoneAuditLog.edited_by.
        sa.Column("acknowledged_by", UUID(as_uuid=True), nullable=True),
        # Reserved for WhatsApp/push delivery, not wired yet.
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_events_org_event_time", "events", ["org_id", sa.text("event_time DESC")])
    op.create_index("ix_events_vehicle_type_open", "events", ["vehicle_id", "event_type", "ended_at"])

    # Independent per-vehicle ordering guard, decoupled from VehicleTripState so event
    # detection stays correct for vehicle types the trip engine never touches (bowsers,
    # excavators, drills, surface miners).
    op.create_table(
        "vehicle_event_state",
        sa.Column("vehicle_id", UUID(as_uuid=True), sa.ForeignKey("vehicles.id"), primary_key=True),
        sa.Column("last_processed_event_time", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("zones", sa.Column("speed_limit_kmph", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("zones", "speed_limit_kmph")
    op.drop_table("vehicle_event_state")
    op.drop_index("ix_events_vehicle_type_open", table_name="events")
    op.drop_index("ix_events_org_event_time", table_name="events")
    op.drop_table("events")
    EVENT_SEVERITY_ENUM.drop(op.get_bind(), checkfirst=True)
    EVENT_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)
