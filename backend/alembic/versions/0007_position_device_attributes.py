"""capture ignition/battery/fuel/driver attributes Traccar already forwards

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-18

"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable, forward-compat plumbing: real firmware doesn't send these yet
    # (firmware/sketch_jul10a/transport.h's own comment — "omitted until those sensors
    # land later in Phase 1"), but the simulator already does, and Traccar's OsmAnd
    # decoder forwards them under these exact attribute keys (verified against a stored
    # Position.raw payload: ignition, batteryLevel, fuel, driver). No detector reads
    # these yet — that's the fuel classifier / driver-session phases, deliberately out
    # of scope here (see CLAUDE.md's Option A scope decision).
    op.add_column("positions", sa.Column("ignition", sa.Boolean(), nullable=True))
    op.add_column("positions", sa.Column("battery_level", sa.Float(), nullable=True))
    # "raw": uncalibrated sensor value (0-100 potentiometer today, volts/RS485 later) —
    # the litres conversion is the fuel classifier's job, not ingestion's.
    op.add_column("positions", sa.Column("fuel_raw", sa.Float(), nullable=True))
    op.add_column("positions", sa.Column("driver_uid", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("positions", "driver_uid")
    op.drop_column("positions", "fuel_raw")
    op.drop_column("positions", "battery_level")
    op.drop_column("positions", "ignition")
