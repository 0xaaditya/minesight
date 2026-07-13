"""initial schema: organizations, vehicles, positions

Revision ID: 0001
Revises:
Create Date: 2026-07-10

"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

VEHICLE_TYPE_ENUM = sa.Enum(
    "tipper", "excavator", "loader", "bowser", "drill", "surface_miner",
    name="vehicletype",
)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "vehicles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("asset_id", sa.String(), nullable=False, unique=True),
        sa.Column("vehicle_type", VEHICLE_TYPE_ENUM, nullable=False),
        sa.Column("traccar_unique_id", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "positions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("vehicle_id", UUID(as_uuid=True), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("speed_knots", sa.Float(), nullable=True),
        sa.Column("course", sa.Float(), nullable=True),
        sa.Column("hdop", sa.Float(), nullable=True),
        sa.Column("satellites", sa.Integer(), nullable=True),
        sa.Column("raw", JSONB(), nullable=True),
    )
    op.create_index(
        "ix_positions_vehicle_event_time", "positions", ["vehicle_id", "event_time"]
    )

    # Seed the default org (multi-tenant column exists everywhere per CLAUDE.md,
    # even though there's no multi-org UI/auth yet).
    default_org_id = str(uuid.uuid4())
    op.execute(
        sa.text(
            "INSERT INTO organizations (id, name, created_at) "
            "VALUES (CAST(:id AS UUID), 'Default Org', now())"
        ).bindparams(id=default_org_id)
    )


def downgrade() -> None:
    op.drop_index("ix_positions_vehicle_event_time", table_name="positions")
    op.drop_table("positions")
    op.drop_table("vehicles")
    VEHICLE_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)
    op.drop_table("organizations")
