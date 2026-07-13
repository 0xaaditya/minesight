"""zones, zone audit log, trips, vehicle trip state

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-11

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ZONE_TYPE_ENUM = sa.Enum("loading", "dumping", "parking", "no_go", name="zonetype")
ZONE_AUDIT_ACTION_ENUM = sa.Enum("create", "update", "close", name="zoneauditaction")
TRIP_CYCLE_STATUS_ENUM = sa.Enum(
    "idle", "loading", "hauling", "dumping", "returning", "breakdown", name="tripcyclestatus"
)
TRIP_ROW_STATUS_ENUM = sa.Enum("in_progress", "completed", "aborted", name="triprowstatus")


def upgrade() -> None:
    op.create_table(
        "zones",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("zone_key", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("zone_type", ZONE_TYPE_ENUM, nullable=False),
        sa.Column("geometry", JSONB(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_zones_zone_key", "zones", ["zone_key"])

    op.create_table(
        "zone_audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("zone_key", UUID(as_uuid=True), nullable=False),
        sa.Column("action", ZONE_AUDIT_ACTION_ENUM, nullable=False),
        sa.Column("old_value", JSONB(), nullable=True),
        sa.Column("new_value", JSONB(), nullable=True),
        sa.Column("edited_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_zone_audit_log_zone_key", "zone_audit_log", ["zone_key"])

    op.create_table(
        "trips",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("vehicle_id", UUID(as_uuid=True), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("cycle_number", sa.Integer(), nullable=True),
        sa.Column("load_zone_id", UUID(as_uuid=True), sa.ForeignKey("zones.id"), nullable=True),
        sa.Column(
            "load_excavator_vehicle_id", UUID(as_uuid=True), sa.ForeignKey("vehicles.id"), nullable=True
        ),
        sa.Column("dump_zone_id", UUID(as_uuid=True), sa.ForeignKey("zones.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dumped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", TRIP_ROW_STATUS_ENUM, nullable=False, server_default="in_progress"),
        sa.Column("had_anomalous_entry", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint(
            # Normal trips have exactly one load reference. The one exception: a vehicle
            # reaching DUMPING without ever passing through LOADING first (anomalous —
            # e.g. skipped/mis-reported) has no valid load ref to record; that case is
            # only allowed when had_anomalous_entry is set, so the flag and the missing
            # reference always travel together rather than looking like silent data loss.
            "(had_anomalous_entry = true AND load_zone_id IS NULL AND load_excavator_vehicle_id IS NULL) "
            "OR (had_anomalous_entry = false AND "
            "(CASE WHEN load_zone_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN load_excavator_vehicle_id IS NOT NULL THEN 1 ELSE 0 END) = 1)",
            name="ck_trip_load_ref_matches_anomaly_flag",
        ),
    )
    op.create_index("ix_trips_vehicle_id", "trips", ["vehicle_id"])

    op.create_table(
        "vehicle_trip_state",
        sa.Column("vehicle_id", UUID(as_uuid=True), sa.ForeignKey("vehicles.id"), primary_key=True),
        sa.Column("trip_status", TRIP_CYCLE_STATUS_ENUM, nullable=True),
        sa.Column("trip_status_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_moving_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_processed_event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_trip_id", UUID(as_uuid=True), sa.ForeignKey("trips.id"), nullable=True),
        sa.Column("paired_excavator_id", UUID(as_uuid=True), sa.ForeignKey("vehicles.id"), nullable=True),
        sa.Column("pre_breakdown_status", TRIP_CYCLE_STATUS_ENUM, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("vehicle_trip_state")
    op.drop_index("ix_trips_vehicle_id", table_name="trips")
    op.drop_table("trips")
    op.drop_index("ix_zone_audit_log_zone_key", table_name="zone_audit_log")
    op.drop_table("zone_audit_log")
    op.drop_index("ix_zones_zone_key", table_name="zones")
    op.drop_table("zones")
    TRIP_ROW_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
    TRIP_CYCLE_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
    ZONE_AUDIT_ACTION_ENUM.drop(op.get_bind(), checkfirst=True)
    ZONE_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)
