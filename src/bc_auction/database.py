from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine, make_url

metadata = MetaData()

scrape_runs = Table(
    "scrape_runs",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, default=uuid4),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("status", String(16), nullable=False),
    Column("mode", String(32), nullable=False),
    Column("requested_limit", Integer, nullable=False),
    Column("keyword", Text, nullable=False),
    Column("sort", String(64), nullable=False),
    Column("pages_visited", Integer, nullable=False, server_default="0"),
    Column("items_seen", Integer, nullable=False, server_default="0"),
    Column("items_created", Integer, nullable=False, server_default="0"),
    Column("items_updated", Integer, nullable=False, server_default="0"),
    Column("observations_created", Integer, nullable=False, server_default="0"),
    Column("item_failures", Integer, nullable=False, server_default="0"),
    Column("parser_version", String(64), nullable=False),
    Column("error_summary", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("status IN ('running', 'succeeded', 'partial', 'failed')"),
    CheckConstraint(
        "(status = 'running' AND finished_at IS NULL) OR "
        "(status IN ('succeeded', 'partial', 'failed') AND finished_at IS NOT NULL)",
        name="ck_scrape_runs_status_finished_at",
    ),
)

auction_items = Table(
    "auction_items",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, default=uuid4),
    Column("source_id", String(64), nullable=False, unique=True),
    Column("source_dis_id", String(64), nullable=False, unique=True),
    Column("canonical_source_url", Text, nullable=False, unique=True),
    Column("title", Text, nullable=False),
    Column("description", Text),
    Column("category_raw", Text),
    Column("category_canonical", Text),
    Column("location_raw", Text),
    Column("location_canonical", Text),
    Column("location_qualifier", Text),
    Column("location_normalization_status", String(16)),
    Column("pickup_details", Text),
    Column("image_urls", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("status", String(16), nullable=False),
    Column("status_raw", Text),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_changed_at", DateTime(timezone=True), nullable=False),
    Column("closed_at", DateTime(timezone=True)),
    Column("metadata_hash", String(64), nullable=False),
    Column("current_observation_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("status IN ('open', 'closed', 'withdrawn', 'unknown')"),
    CheckConstraint(
        "location_normalization_status IS NULL OR "
        "location_normalization_status IN ('exact', 'alias', 'unknown')"
    ),
)

item_observations = Table(
    "item_observations",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, default=uuid4),
    Column("auction_item_id", Uuid(as_uuid=True), ForeignKey("auction_items.id"), nullable=False),
    Column("scrape_run_id", Uuid(as_uuid=True), ForeignKey("scrape_runs.id"), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("current_bid", Numeric(14, 2)),
    Column("minimum_bid", Numeric(14, 2)),
    Column("starting_bid", Numeric(14, 2)),
    Column("bid_count", Integer),
    Column("closing_at", DateTime(timezone=True)),
    Column("status", String(16), nullable=False),
    Column("observation_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("status IN ('open', 'closed', 'withdrawn', 'unknown')"),
    UniqueConstraint(
        "auction_item_id",
        "observed_at",
        "observation_hash",
        name="uq_item_observations_item_observed_hash",
    ),
)

Index(
    "ix_item_observations_item_observed",
    item_observations.c.auction_item_id,
    item_observations.c.observed_at,
)
Index("ix_item_observations_closing_at", item_observations.c.closing_at)

location_aliases = Table(
    "location_aliases",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, default=uuid4),
    Column("raw_value", Text, nullable=False),
    Column("normalized_key", Text, nullable=False, unique=True),
    Column("canonical_value", Text, nullable=False),
    Column("qualifier", Text),
    Column("region", Text),
    Column("status", String(16), nullable=False),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("status IN ('known', 'review', 'ignored')"),
)


class DatabaseConfigurationError(ValueError):
    pass


def create_postgres_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise DatabaseConfigurationError("database URL must use PostgreSQL")
    return create_engine(url, pool_pre_ping=True)


def utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
