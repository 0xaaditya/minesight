"""trip lead distance (haul_distance_m) and full trip path distance

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-13

"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Lead distance (loaded_at -> dumped_at breadcrumb path, set at cycle++) and full
    # trip-row path distance (started_at -> completed_at, set at completion). Nullable:
    # pre-existing trips and anomalous entries have no value to backfill.
    op.add_column("trips", sa.Column("haul_distance_m", sa.Float(), nullable=True))
    op.add_column("trips", sa.Column("trip_distance_m", sa.Float(), nullable=True))
    # Traccar's cumulative odometer (totalDistance attribute, meters) captured per
    # position — distance deltas come from this, not a re-summed breadcrumb.
    op.add_column("positions", sa.Column("total_distance_m", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("positions", "total_distance_m")
    op.drop_column("trips", "trip_distance_m")
    op.drop_column("trips", "haul_distance_m")
