"""Create persistence and observation-history tables.

Revision ID: 20260715_01
Revises:
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260715_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.Text(), nullable=False),
        sa.Column("sort", sa.String(length=64), nullable=False),
        sa.Column("pages_visited", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("observations_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("item_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'partial', 'failed')"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "auction_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("source_dis_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_source_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category_raw", sa.Text(), nullable=True),
        sa.Column("category_canonical", sa.Text(), nullable=True),
        sa.Column("location_raw", sa.Text(), nullable=True),
        sa.Column("location_canonical", sa.Text(), nullable=True),
        sa.Column("location_qualifier", sa.Text(), nullable=True),
        sa.Column("location_normalization_status", sa.String(length=16), nullable=True),
        sa.Column("pickup_details", sa.Text(), nullable=True),
        sa.Column(
            "image_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("status_raw", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('open', 'closed', 'withdrawn', 'unknown')"),
        sa.CheckConstraint(
            "location_normalization_status IS NULL OR "
            "location_normalization_status IN ('exact', 'alias', 'unknown')"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id"),
        sa.UniqueConstraint("source_dis_id"),
        sa.UniqueConstraint("canonical_source_url"),
    )
    op.create_table(
        "item_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("auction_item_id", sa.Uuid(), nullable=False),
        sa.Column("scrape_run_id", sa.Uuid(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_bid", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("minimum_bid", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("starting_bid", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("bid_count", sa.Integer(), nullable=True),
        sa.Column("closing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("observation_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('open', 'closed', 'withdrawn', 'unknown')"),
        sa.ForeignKeyConstraint(["auction_item_id"], ["auction_items.id"]),
        sa.ForeignKeyConstraint(["scrape_run_id"], ["scrape_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_item_observations_item_observed",
        "item_observations",
        ["auction_item_id", "observed_at"],
    )
    op.create_index("ix_item_observations_closing_at", "item_observations", ["closing_at"])
    op.create_table(
        "location_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("normalized_key", sa.Text(), nullable=False),
        sa.Column("canonical_value", sa.Text(), nullable=False),
        sa.Column("qualifier", sa.Text(), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('known', 'review', 'ignored')"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_key"),
    )


def downgrade() -> None:
    op.drop_table("location_aliases")
    op.drop_index("ix_item_observations_closing_at", table_name="item_observations")
    op.drop_index("ix_item_observations_item_observed", table_name="item_observations")
    op.drop_table("item_observations")
    op.drop_table("auction_items")
    op.drop_table("scrape_runs")
