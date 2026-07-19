"""Add complete-refresh coverage and inventory freshness state.

Revision ID: 20260718_06
Revises: 20260717_05
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260718_06"
down_revision: str | None = "20260717_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_COUNTERS = (
    "expected_product_groups",
    "processed_product_groups",
    "unique_listings_enumerated",
    "duplicate_listings_enumerated",
    "detail_attempted",
    "detail_succeeded",
    "persistence_succeeded",
    "persistence_failures",
)


def upgrade() -> None:
    op.add_column(
        "scrape_runs",
        sa.Column(
            "completion_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
    )
    for column in _RUN_COUNTERS:
        op.add_column(
            "scrape_runs",
            sa.Column(column, sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_check_constraint(
            f"ck_scrape_runs_{column}_nonnegative", "scrape_runs", f"{column} >= 0"
        )
    op.add_column(
        "scrape_runs",
        sa.Column("enumeration_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "ck_scrape_runs_completion_status",
        "scrape_runs",
        "completion_status IN ('pending', 'complete', 'incomplete')",
    )

    op.add_column("auction_items", sa.Column("last_complete_seen_at", sa.DateTime(timezone=True)))
    op.add_column(
        "auction_items",
        sa.Column("complete_absence_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "auction_items",
        sa.Column(
            "inventory_state",
            sa.String(length=16),
            nullable=False,
            server_default="current",
        ),
    )
    op.add_column("auction_items", sa.Column("first_absent_at", sa.DateTime(timezone=True)))
    op.add_column("auction_items", sa.Column("stale_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_auction_items_absences_nonnegative", "auction_items", "complete_absence_count >= 0"
    )
    op.create_check_constraint(
        "ck_auction_items_inventory_state",
        "auction_items",
        "inventory_state IN ('current', 'not_observed', 'stale')",
    )
    op.create_index("ix_auction_items_inventory_state", "auction_items", ["inventory_state"])


def downgrade() -> None:
    op.drop_index("ix_auction_items_inventory_state", table_name="auction_items")
    op.drop_constraint("ck_auction_items_inventory_state", "auction_items", type_="check")
    op.drop_constraint("ck_auction_items_absences_nonnegative", "auction_items", type_="check")
    for column in (
        "stale_at",
        "first_absent_at",
        "inventory_state",
        "complete_absence_count",
        "last_complete_seen_at",
    ):
        op.drop_column("auction_items", column)
    op.drop_constraint("ck_scrape_runs_completion_status", "scrape_runs", type_="check")
    op.drop_column("scrape_runs", "enumeration_complete")
    for column in reversed(_RUN_COUNTERS):
        op.drop_constraint(f"ck_scrape_runs_{column}_nonnegative", "scrape_runs", type_="check")
        op.drop_column("scrape_runs", column)
    op.drop_column("scrape_runs", "completion_status")
