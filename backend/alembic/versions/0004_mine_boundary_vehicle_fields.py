"""mine_boundary zone type + vehicle registry fields (registration_number, manufacturer, capacity_tonnes)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-14

"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Site perimeter zone type. Postgres 12+ allows ADD VALUE inside a transaction as
    # long as the same transaction doesn't USE the new value (this migration doesn't).
    # On PG <12 this would need to run outside a transaction (autocommit).
    op.execute("ALTER TYPE zonetype ADD VALUE IF NOT EXISTS 'mine_boundary'")

    # Manual registry fields for now; schema-ready for a future VAHAN RC-lookup API
    # that would auto-fill them from the plate number. Manufacturer matters beyond
    # display: some makes (e.g. Volvo) carry factory weigh sensors, which changes how
    # our device gets configured/attached on install.
    op.add_column("vehicles", sa.Column("registration_number", sa.String(), nullable=True))
    op.add_column("vehicles", sa.Column("manufacturer", sa.String(), nullable=True))
    op.add_column("vehicles", sa.Column("capacity_tonnes", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("vehicles", "capacity_tonnes")
    op.drop_column("vehicles", "manufacturer")
    op.drop_column("vehicles", "registration_number")
    # Postgres cannot remove a value from an enum type — 'mine_boundary' stays in
    # zonetype on downgrade. Harmless: no rows reference it after the app code reverts.
