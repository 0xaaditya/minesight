"""vehicle soft-delete (deactivated_at)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-14

"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Mirrors the Zone versioning idiom (valid_to = closed): a vehicle with trip/
    # position history is never hard-deleted (that history is legal evidence per
    # CLAUDE.md), it's deactivated instead and excluded from the default list. Only a
    # vehicle with zero history — a mis-typed registration — is actually removed by
    # DELETE /vehicles/{id}.
    op.add_column("vehicles", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("vehicles", "deactivated_at")
