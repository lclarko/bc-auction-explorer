from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
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
    Column("completion_status", String(16), nullable=False, server_default="pending"),
    Column("expected_product_groups", Integer, nullable=False, server_default="0"),
    Column("processed_product_groups", Integer, nullable=False, server_default="0"),
    Column("unique_listings_enumerated", Integer, nullable=False, server_default="0"),
    Column("duplicate_listings_enumerated", Integer, nullable=False, server_default="0"),
    Column("detail_attempted", Integer, nullable=False, server_default="0"),
    Column("detail_succeeded", Integer, nullable=False, server_default="0"),
    Column("persistence_succeeded", Integer, nullable=False, server_default="0"),
    Column("persistence_failures", Integer, nullable=False, server_default="0"),
    Column("enumeration_complete", Boolean, nullable=False, server_default="false"),
    Column("pages_visited", Integer, nullable=False, server_default="0"),
    Column("items_seen", Integer, nullable=False, server_default="0"),
    Column("items_created", Integer, nullable=False, server_default="0"),
    Column("items_updated", Integer, nullable=False, server_default="0"),
    Column("observations_created", Integer, nullable=False, server_default="0"),
    Column("item_failures", Integer, nullable=False, server_default="0"),
    Column("source_requests", Integer, nullable=False, server_default="0"),
    Column("source_responses", Integer, nullable=False, server_default="0"),
    Column("source_retries", Integer, nullable=False, server_default="0"),
    Column("rate_limit_responses", Integer, nullable=False, server_default="0"),
    Column("source_transport_errors", Integer, nullable=False, server_default="0"),
    Column("source_request_duration_ms", Integer, nullable=False, server_default="0"),
    Column("source_request_wait_duration_ms", Integer, nullable=False, server_default="0"),
    Column("source_retry_wait_duration_ms", Integer, nullable=False, server_default="0"),
    Column("parser_version", String(64), nullable=False),
    Column("error_summary", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("status IN ('running', 'succeeded', 'partial', 'failed')"),
    CheckConstraint(
        "completion_status IN ('pending', 'complete', 'incomplete')",
        name="ck_scrape_runs_completion_status",
    ),
    CheckConstraint(
        "(status = 'running' AND finished_at IS NULL) OR "
        "(status IN ('succeeded', 'partial', 'failed') AND finished_at IS NOT NULL)",
        name="ck_scrape_runs_status_finished_at",
    ),
    CheckConstraint("source_requests >= 0", name="ck_scrape_runs_source_requests_nonnegative"),
    CheckConstraint("source_responses >= 0", name="ck_scrape_runs_source_responses_nonnegative"),
    CheckConstraint("source_retries >= 0", name="ck_scrape_runs_source_retries_nonnegative"),
    CheckConstraint(
        "rate_limit_responses >= 0",
        name="ck_scrape_runs_rate_limit_responses_nonnegative",
    ),
    CheckConstraint(
        "source_transport_errors >= 0",
        name="ck_scrape_runs_source_transport_errors_nonnegative",
    ),
    CheckConstraint(
        "source_request_duration_ms >= 0",
        name="ck_scrape_runs_source_request_duration_ms_nonnegative",
    ),
    CheckConstraint(
        "source_request_wait_duration_ms >= 0",
        name="ck_scrape_runs_source_request_wait_duration_ms_nonnegative",
    ),
    CheckConstraint(
        "source_retry_wait_duration_ms >= 0",
        name="ck_scrape_runs_source_retry_wait_duration_ms_nonnegative",
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
    Column("last_complete_seen_at", DateTime(timezone=True)),
    Column("complete_absence_count", Integer, nullable=False, server_default="0"),
    Column("inventory_state", String(16), nullable=False, server_default="current"),
    Column("first_absent_at", DateTime(timezone=True)),
    Column("stale_at", DateTime(timezone=True)),
    Column("metadata_hash", String(64), nullable=False),
    Column("current_observation_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("status IN ('open', 'closed', 'withdrawn', 'unknown')"),
    CheckConstraint("complete_absence_count >= 0", name="ck_auction_items_absences_nonnegative"),
    CheckConstraint(
        "inventory_state IN ('current', 'not_observed', 'stale')",
        name="ck_auction_items_inventory_state",
    ),
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
