import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import Connection, Engine, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import IntegrityError

from bc_auction.database import (
    auction_items,
    item_observations,
    location_aliases,
    scrape_runs,
    utc_now,
)
from bc_auction.locations import LocationNormalizer
from bc_auction.models import AuctionDetailRecord, AuctionStatus, LocationStatus
from bc_auction.urls import canonicalize_source_url, extract_source_dis_id, normalize_public_url


class ScrapeRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class PersistenceError(RuntimeError):
    pass


class IdentityConflictError(PersistenceError):
    pass


class PersistedAuctionRecord(BaseModel):
    """The parser-independent data accepted by the persistence repository."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    source_dis_id: str = Field(min_length=1)
    canonical_source_url: str
    title: str = Field(min_length=1)
    description: str | None = None
    category_raw: str | None = None
    category_canonical: str | None = None
    location_raw: str | None = None
    location_canonical: str | None = None
    location_qualifier: str | None = None
    location_normalization_status: LocationStatus | None = None
    pickup_details: str | None = None
    image_urls: tuple[str, ...] = ()
    current_bid: Decimal | None = Field(default=None, ge=0)
    minimum_bid: Decimal | None = Field(default=None, ge=0)
    starting_bid: Decimal | None = Field(default=None, ge=0)
    bid_count: int | None = Field(default=None, ge=0)
    closing_at: datetime | None = None
    status_raw: str | None = None
    status: AuctionStatus
    observed_at: datetime
    metadata_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("canonical_source_url")
    @classmethod
    def require_canonical_source_url(cls, value: str) -> str:
        if canonicalize_source_url(value) != value:
            raise ValueError("canonical source URL must be session-free and normalized")
        return value

    @model_validator(mode="after")
    def require_display_id_matches_canonical_url(self) -> "PersistedAuctionRecord":
        if extract_source_dis_id(self.canonical_source_url) != self.source_dis_id:
            raise ValueError("source display ID did not match the canonical source URL")
        return self

    @field_validator("image_urls")
    @classmethod
    def require_normalized_image_urls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(normalize_public_url(image_url) != image_url for image_url in value):
            raise ValueError("image URLs must be session-free and normalized")
        return value

    @field_validator("closing_at", "observed_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("datetime must include a timezone")
        return value


class _PersistenceInput(TypedDict):
    source_id: str
    source_dis_id: str
    canonical_source_url: str
    title: str
    description: str | None
    category_raw: str | None
    category_canonical: str | None
    location_raw: str | None
    location_canonical: str | None
    location_qualifier: str | None
    location_normalization_status: LocationStatus | None
    pickup_details: str | None
    image_urls: tuple[str, ...]
    current_bid: Decimal | None
    minimum_bid: Decimal | None
    starting_bid: Decimal | None
    bid_count: int | None
    closing_at: datetime | None
    status_raw: str | None
    status: AuctionStatus
    observed_at: datetime


def convert_reconciled_record(
    record: AuctionDetailRecord,
    *,
    observed_at: datetime,
    normalizer: LocationNormalizer | None = None,
) -> PersistedAuctionRecord:
    """Create persistence input from a successful search-detail reconciliation."""
    if record.canonical_source_url is None:
        raise PersistenceError("reconciled record did not include a canonical source URL")
    if observed_at.tzinfo is None:
        raise PersistenceError("observation time must include a timezone")

    canonical_url = str(record.canonical_source_url)
    location = None
    if record.location_raw is not None:
        location = (normalizer or LocationNormalizer()).normalize(record.location_raw)

    data: _PersistenceInput = {
        "source_id": record.source_id,
        "source_dis_id": extract_source_dis_id(canonical_url),
        "canonical_source_url": canonical_url,
        "title": record.title,
        "description": record.description,
        "category_raw": record.category_raw,
        "category_canonical": None,
        "location_raw": record.location_raw,
        "location_canonical": location.canonical if location is not None else None,
        "location_qualifier": location.qualifier if location is not None else None,
        "location_normalization_status": location.status if location is not None else None,
        "pickup_details": record.pickup_details,
        "image_urls": tuple(str(image_url) for image_url in record.image_urls),
        "current_bid": record.current_bid,
        "minimum_bid": record.minimum_bid,
        "starting_bid": None,
        "bid_count": record.bid_count,
        "closing_at": record.closing_at,
        "status_raw": record.status_raw,
        "status": record.status,
        "observed_at": observed_at,
    }
    return _persisted_record(data)


def _persisted_record(data: _PersistenceInput) -> PersistedAuctionRecord:
    return PersistedAuctionRecord(
        **data,
        metadata_hash=metadata_hash(data),
        observation_hash=observation_hash(data),
    )


def _persistence_input_from_record(record: PersistedAuctionRecord) -> _PersistenceInput:
    return {
        "source_id": record.source_id,
        "source_dis_id": record.source_dis_id,
        "canonical_source_url": record.canonical_source_url,
        "title": record.title,
        "description": record.description,
        "category_raw": record.category_raw,
        "category_canonical": record.category_canonical,
        "location_raw": record.location_raw,
        "location_canonical": record.location_canonical,
        "location_qualifier": record.location_qualifier,
        "location_normalization_status": record.location_normalization_status,
        "pickup_details": record.pickup_details,
        "image_urls": record.image_urls,
        "current_bid": record.current_bid,
        "minimum_bid": record.minimum_bid,
        "starting_bid": record.starting_bid,
        "bid_count": record.bid_count,
        "closing_at": record.closing_at,
        "status_raw": record.status_raw,
        "status": record.status,
        "observed_at": record.observed_at,
    }


def metadata_hash(data: _PersistenceInput) -> str:
    return _hash(
        {
            "title": data["title"],
            "description": data["description"],
            "category_raw": data["category_raw"],
            "category_canonical": data["category_canonical"],
            "location_raw": data["location_raw"],
            "location_canonical": data["location_canonical"],
            "location_qualifier": data["location_qualifier"],
            "location_normalization_status": data["location_normalization_status"],
            "pickup_details": data["pickup_details"],
            "image_urls": data["image_urls"],
        }
    )


def observation_hash(data: _PersistenceInput) -> str:
    return _hash(
        {
            "current_bid": data["current_bid"],
            "minimum_bid": data["minimum_bid"],
            "starting_bid": data["starting_bid"],
            "bid_count": data["bid_count"],
            "closing_at": data["closing_at"],
            "status": data["status"],
        }
    )


def _hash(payload: dict[str, object]) -> str:
    serialized = json.dumps(
        payload,
        default=_json_value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _json_value(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"unsupported hash value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class PersistResult:
    created: bool
    updated: bool
    observation_created: bool


@dataclass(frozen=True, slots=True)
class ScrapeRunInput:
    requested_limit: int
    keyword: str
    sort: str
    parser_version: str
    mode: str = "detail"


@dataclass(frozen=True, slots=True)
class ScrapeRunCounts:
    pages_visited: int
    items_seen: int
    items_created: int
    items_updated: int
    observations_created: int
    item_failures: int


@dataclass(frozen=True, slots=True)
class ScrapeRunMetrics:
    source_requests: int = 0
    source_responses: int = 0
    source_retries: int = 0
    rate_limit_responses: int = 0
    source_transport_errors: int = 0
    source_request_duration_ms: int = 0
    source_request_wait_duration_ms: int = 0
    source_retry_wait_duration_ms: int = 0


class AuctionRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ping(self) -> None:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def start_scrape_run(
        self,
        run: ScrapeRunInput,
        *,
        started_at: datetime | None = None,
    ) -> UUID:
        timestamp = started_at or utc_now()
        from uuid import uuid4

        run_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(
                insert(scrape_runs).values(
                    id=run_id,
                    started_at=timestamp,
                    status=ScrapeRunStatus.RUNNING.value,
                    mode=run.mode,
                    requested_limit=run.requested_limit,
                    keyword=run.keyword,
                    sort=run.sort,
                    parser_version=run.parser_version,
                    created_at=timestamp,
                )
            )
        return run_id

    def finish_scrape_run(
        self,
        run_id: UUID,
        *,
        status: ScrapeRunStatus,
        counts: ScrapeRunCounts,
        metrics: ScrapeRunMetrics | None = None,
        error_summary: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        if status is ScrapeRunStatus.RUNNING:
            raise ValueError("running scrape run cannot be finalized")
        final_metrics = metrics or ScrapeRunMetrics()
        with self._engine.begin() as connection:
            connection.execute(
                update(scrape_runs)
                .where(scrape_runs.c.id == run_id)
                .values(
                    finished_at=finished_at or utc_now(),
                    status=status.value,
                    pages_visited=counts.pages_visited,
                    items_seen=counts.items_seen,
                    items_created=counts.items_created,
                    items_updated=counts.items_updated,
                    observations_created=counts.observations_created,
                    item_failures=counts.item_failures,
                    source_requests=final_metrics.source_requests,
                    source_responses=final_metrics.source_responses,
                    source_retries=final_metrics.source_retries,
                    rate_limit_responses=final_metrics.rate_limit_responses,
                    source_transport_errors=final_metrics.source_transport_errors,
                    source_request_duration_ms=final_metrics.source_request_duration_ms,
                    source_request_wait_duration_ms=final_metrics.source_request_wait_duration_ms,
                    source_retry_wait_duration_ms=final_metrics.source_retry_wait_duration_ms,
                    error_summary=error_summary,
                )
            )

    def persist_reconciled_record(
        self,
        run_id: UUID,
        record: PersistedAuctionRecord,
    ) -> PersistResult:
        try:
            record = PersistedAuctionRecord.model_validate(record.model_dump())
            record = _persisted_record(_persistence_input_from_record(record))
        except ValidationError:
            raise PersistenceError("persistence record failed validation") from None
        try:
            with self._engine.begin() as connection:
                return self._persist_record(connection, run_id, record)
        except IntegrityError as exc:
            raise PersistenceError("database rejected auction persistence") from exc

    def _persist_record(
        self,
        connection: Connection,
        run_id: UUID,
        record: PersistedAuctionRecord,
    ) -> PersistResult:
        existing = connection.execute(
            select(auction_items).where(auction_items.c.source_id == record.source_id)
        ).mappings().one_or_none()
        conflicting = connection.execute(
            select(auction_items.c.source_id).where(
                (auction_items.c.source_dis_id == record.source_dis_id)
                | (auction_items.c.canonical_source_url == record.canonical_source_url)
            )
        ).scalar_one_or_none()
        if conflicting is not None and conflicting != record.source_id:
            raise IdentityConflictError("canonical auction identity belongs to another source ID")

        now = record.observed_at
        item_values = _item_values(record)
        if existing is None:
            from uuid import uuid4

            item_id = uuid4()
            connection.execute(
                insert(auction_items).values(
                    id=item_id,
                    **item_values,
                    first_seen_at=now,
                    last_seen_at=now,
                    last_changed_at=now,
                    closed_at=now if _is_terminal(record.status) else None,
                    created_at=now,
                    updated_at=now,
                )
            )
            observation_created = self._insert_observation(connection, item_id, run_id, record)
            self._record_location_alias(connection, record)
            return PersistResult(
                created=True,
                updated=False,
                observation_created=observation_created,
            )

        item_id = existing["id"]
        # BC Auction can revise a public display document while retaining its auction number.
        identity_changed = (
            existing["source_dis_id"] != record.source_dis_id
            or existing["canonical_source_url"] != record.canonical_source_url
        )
        if record.observed_at < existing["last_seen_at"]:
            observation_created = self._insert_stale_observation_if_new(
                connection,
                item_id,
                run_id,
                record,
            )
            return PersistResult(
                created=False,
                updated=False,
                observation_created=observation_created,
            )
        if _is_terminal(existing["status"]) and not _is_terminal(record.status):
            observation_created = self._record_nonterminal_history_after_closure(
                connection,
                item_id,
                run_id,
                record,
            )
            connection.execute(
                update(auction_items)
                .where(auction_items.c.id == item_id)
                .values(
                    source_dis_id=record.source_dis_id,
                    canonical_source_url=record.canonical_source_url,
                    last_seen_at=now,
                    last_changed_at=now if identity_changed else existing["last_changed_at"],
                    updated_at=now,
                )
            )
            return PersistResult(
                created=False,
                updated=identity_changed,
                observation_created=observation_created,
            )
        metadata_changed = existing["metadata_hash"] != record.metadata_hash
        observation_changed = existing["current_observation_hash"] != record.observation_hash
        closed_at = _first_terminal_observed_at(existing["closed_at"], record)
        closed_at_changed = closed_at != existing["closed_at"]

        connection.execute(
            update(auction_items)
            .where(auction_items.c.id == item_id)
            .values(
                **item_values,
                last_seen_at=now,
                last_changed_at=(
                    now
                    if (
                        identity_changed
                        or metadata_changed
                        or observation_changed
                        or closed_at_changed
                    )
                    else existing["last_changed_at"]
                ),
                closed_at=closed_at,
                updated_at=now,
            )
        )
        observation_created = (
            self._insert_observation(connection, item_id, run_id, record)
            if observation_changed
            else False
        )
        self._record_location_alias(connection, record)
        return PersistResult(
            created=False,
            updated=(
                identity_changed or metadata_changed or observation_changed or closed_at_changed
            ),
            observation_created=observation_created,
        )

    def _record_nonterminal_history_after_closure(
        self,
        connection: Connection,
        item_id: UUID,
        run_id: UUID,
        record: PersistedAuctionRecord,
    ) -> bool:
        latest_history_hash = connection.execute(
            select(item_observations.c.observation_hash)
            .where(item_observations.c.auction_item_id == item_id)
            .order_by(
                item_observations.c.observed_at.desc(),
                item_observations.c.created_at.desc(),
                item_observations.c.observation_hash.desc(),
            )
            .limit(1)
        ).scalar_one_or_none()
        if latest_history_hash == record.observation_hash:
            return False
        return self._insert_observation(connection, item_id, run_id, record)

    def _insert_stale_observation_if_new(
        self,
        connection: Connection,
        item_id: UUID,
        run_id: UUID,
        record: PersistedAuctionRecord,
    ) -> bool:
        return self._insert_observation(connection, item_id, run_id, record)

    def _insert_observation(
        self,
        connection: Connection,
        item_id: UUID,
        run_id: UUID,
        record: PersistedAuctionRecord,
    ) -> bool:
        result = connection.execute(
            postgres_insert(item_observations)
            .values(**_observation_values(item_id, run_id, record))
            .on_conflict_do_nothing(constraint="uq_item_observations_item_observed_hash")
            .returning(item_observations.c.id)
        )
        return result.scalar_one_or_none() is not None

    def _record_location_alias(
        self,
        connection: Connection,
        record: PersistedAuctionRecord,
    ) -> None:
        if record.location_raw is None or record.location_canonical is None:
            return
        timestamp = record.observed_at
        status = (
            "known"
            if record.location_normalization_status is not LocationStatus.UNKNOWN
            else "review"
        )
        normalized_key = " ".join(record.location_raw.split()).casefold()
        statement = postgres_insert(location_aliases).values(
            id=_new_uuid(),
            raw_value=record.location_raw,
            normalized_key=normalized_key,
            canonical_value=record.location_canonical,
            qualifier=record.location_qualifier,
            status=status,
            first_seen_at=timestamp,
            last_seen_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[location_aliases.c.normalized_key],
                set_={
                    "canonical_value": record.location_canonical,
                    "qualifier": record.location_qualifier,
                    "status": status,
                    "last_seen_at": timestamp,
                    "updated_at": timestamp,
                },
            )
        )


def _item_values(record: PersistedAuctionRecord) -> dict[str, object]:
    return {
        "source_id": record.source_id,
        "source_dis_id": record.source_dis_id,
        "canonical_source_url": record.canonical_source_url,
        "title": record.title,
        "description": record.description,
        "category_raw": record.category_raw,
        "category_canonical": record.category_canonical,
        "location_raw": record.location_raw,
        "location_canonical": record.location_canonical,
        "location_qualifier": record.location_qualifier,
        "location_normalization_status": (
            record.location_normalization_status.value
            if record.location_normalization_status is not None
            else None
        ),
        "pickup_details": record.pickup_details,
        "image_urls": list(record.image_urls),
        "status": record.status.value,
        "status_raw": record.status_raw,
        "metadata_hash": record.metadata_hash,
        "current_observation_hash": record.observation_hash,
    }


def _observation_values(
    item_id: UUID,
    run_id: UUID,
    record: PersistedAuctionRecord,
) -> dict[str, object]:
    return {
        "id": _new_uuid(),
        "auction_item_id": item_id,
        "scrape_run_id": run_id,
        "observed_at": record.observed_at,
        "current_bid": record.current_bid,
        "minimum_bid": record.minimum_bid,
        "starting_bid": record.starting_bid,
        "bid_count": record.bid_count,
        "closing_at": record.closing_at,
        "status": record.status.value,
        "observation_hash": record.observation_hash,
        "created_at": record.observed_at,
    }


def _is_terminal(status: AuctionStatus | str) -> bool:
    return str(status) in {AuctionStatus.CLOSED.value, AuctionStatus.WITHDRAWN.value}


def _first_terminal_observed_at(
    existing_closed_at: datetime | None,
    record: PersistedAuctionRecord,
) -> datetime | None:
    if existing_closed_at is None and _is_terminal(record.status):
        return record.observed_at
    return existing_closed_at


def _new_uuid() -> UUID:
    from uuid import uuid4

    return uuid4()
