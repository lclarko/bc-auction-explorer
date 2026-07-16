"""Preserve the current observation state alongside history.

Revision ID: 20260716_03
Revises: 20260716_02
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260716_03"
down_revision: str | None = "20260716_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "auction_items",
        sa.Column("current_observation_hash", sa.String(length=64), nullable=True),
    )
    op.execute(
        """
        UPDATE auction_items AS item
        SET current_observation_hash = (
            SELECT observation_hash
            FROM item_observations
            WHERE auction_item_id = item.id
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
        )
        """
    )
    op.alter_column("auction_items", "current_observation_hash", nullable=False)


def downgrade() -> None:
    op.drop_column("auction_items", "current_observation_hash")
