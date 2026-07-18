"""Public response models for the read-only auction API."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bc_auction.models import AuctionStatus, LocationStatus
from bc_auction.urls import canonicalize_source_url, normalize_public_url


class ListingSort(StrEnum):
    CLOSING_SOON = "closing_soon"
    CLOSING_LATEST = "closing_latest"
    PRICE_LOW = "price_low"
    PRICE_HIGH = "price_high"
    NEWEST_SEEN = "newest_seen"
    MOST_BIDS = "most_bids"


class ListingView(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
    ALL = "all"


class ListingAvailability(StrEnum):
    ACTIVE = "active"
    SCHEDULED_CLOSING_PASSED = "scheduled_closing_passed"
    CLOSED = "closed"
    WITHDRAWN = "withdrawn"
    UNKNOWN = "unknown"


class ScrapeRunState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _TimestampedModel(_ApiModel):
    @field_validator(
        "first_seen_at",
        "last_seen_at",
        "last_changed_at",
        "closed_at",
        "observed_at",
        "closing_at",
        "started_at",
        "finished_at",
        "latest_listing_seen_at",
        check_fields=False,
    )
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(UTC)


class ListingSummary(_TimestampedModel):
    source_id: str = Field(min_length=1)
    canonical_source_url: str
    title: str = Field(min_length=1)
    category: str | None = None
    location: str | None = None
    location_qualifier: str | None = None
    image_urls: tuple[str, ...] = ()
    current_bid: Decimal | None = Field(default=None, ge=0)
    minimum_bid: Decimal | None = Field(default=None, ge=0)
    starting_bid: Decimal | None = Field(default=None, ge=0)
    bid_count: int | None = Field(default=None, ge=0)
    closing_at: datetime | None = None
    status: AuctionStatus
    availability: ListingAvailability
    observed_at: datetime
    first_seen_at: datetime
    last_seen_at: datetime
    last_changed_at: datetime
    closed_at: datetime | None = None

    @field_validator("canonical_source_url")
    @classmethod
    def require_canonical_source_url(cls, value: str) -> str:
        if canonicalize_source_url(value) != value:
            raise ValueError("canonical source URL must be session-free and normalized")
        return value

    @field_validator("image_urls")
    @classmethod
    def require_public_image_urls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(normalize_public_url(image_url) != image_url for image_url in value):
            raise ValueError("image URLs must be session-free and normalized")
        return value


class ListingDetail(ListingSummary):
    description: str | None = None
    category_raw: str | None = None
    category_canonical: str | None = None
    location_raw: str | None = None
    location_canonical: str | None = None
    location_normalization_status: LocationStatus | None = None
    pickup_details: str | None = None
    status_raw: str | None = None


class PageInfo(_ApiModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class ListingPage(_ApiModel):
    items: tuple[ListingSummary, ...]
    page_info: PageInfo


class Facet(_ApiModel):
    value: str = Field(min_length=1)
    count: int = Field(ge=0)


class FacetList(_ApiModel):
    items: tuple[Facet, ...]


class ScrapeRunSummary(_TimestampedModel):
    started_at: datetime
    finished_at: datetime | None = None
    status: ScrapeRunState
    mode: str
    requested_limit: int = Field(ge=0)
    pages_visited: int = Field(ge=0)
    items_seen: int = Field(ge=0)
    items_created: int = Field(ge=0)
    items_updated: int = Field(ge=0)
    observations_created: int = Field(ge=0)
    item_failures: int = Field(ge=0)
    source_requests: int = Field(ge=0)
    source_responses: int = Field(ge=0)
    source_retries: int = Field(ge=0)
    rate_limit_responses: int = Field(ge=0)
    source_transport_errors: int = Field(ge=0)
    source_request_duration_ms: int = Field(ge=0)
    source_request_wait_duration_ms: int = Field(ge=0)
    source_retry_wait_duration_ms: int = Field(ge=0)


class ScrapeStatus(_TimestampedModel):
    latest_run: ScrapeRunSummary | None = None
    latest_successful_run: ScrapeRunSummary | None = None
    listing_count: int = Field(ge=0)
    latest_listing_seen_at: datetime | None = None


class ApiError(_ApiModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(_ApiModel):
    error: ApiError
