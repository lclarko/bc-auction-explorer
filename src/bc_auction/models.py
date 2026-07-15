from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from bc_auction.urls import canonicalize_source_url, normalize_public_url


class AuctionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    WITHDRAWN = "withdrawn"
    UNKNOWN = "unknown"


class LocationStatus(StrEnum):
    EXACT = "exact"
    ALIAS = "alias"
    UNKNOWN = "unknown"


class NormalizedLocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw: str
    canonical: str
    qualifier: str | None = None
    status: LocationStatus


class SearchResultRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    canonical_source_url: HttpUrl
    request_url: HttpUrl = Field(exclude=True, repr=False)
    title: str | None
    location_raw: str | None = None
    current_bid: Decimal | None = Field(default=None, ge=0)
    minimum_bid: Decimal | None = Field(default=None, ge=0)
    bid_count: int | None = Field(default=None, ge=0)
    closing_at: datetime | None = None
    status_raw: str | None = None
    status: AuctionStatus = AuctionStatus.UNKNOWN
    summary_cells: tuple[str, ...] = ()
    detail_text: str = ""

    @field_validator("closing_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("datetime must include a timezone")
        return value

    @field_validator("canonical_source_url")
    @classmethod
    def require_canonical_source_url(cls, value: HttpUrl) -> HttpUrl:
        if canonicalize_source_url(str(value)) != str(value):
            raise ValueError("canonical source URL must be session-free and normalized")
        return value


class SearchPagination(BaseModel):
    model_config = ConfigDict(frozen=True)

    current_page: int = Field(ge=1)
    record_start: int = Field(ge=1)
    record_end: int = Field(ge=1)
    total_records: int = Field(ge=1)
    request_page_urls: tuple[HttpUrl, ...] = Field(default=(), exclude=True, repr=False)
    next_request_url: HttpUrl | None = Field(default=None, exclude=True, repr=False)


class SearchResultsPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    records: tuple[SearchResultRecord, ...] = ()
    pagination: SearchPagination | None = None


class AuctionDetailRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    canonical_source_url: HttpUrl | None = None
    request_url: HttpUrl = Field(exclude=True, repr=False)
    title: str
    description: str | None = None
    category_raw: str | None = None
    location_raw: str | None = None
    pickup_details: str | None = None
    current_bid: Decimal | None = Field(default=None, ge=0)
    minimum_bid: Decimal | None = Field(default=None, ge=0)
    bid_count: int | None = Field(default=None, ge=0)
    closing_at: datetime | None = None
    status_raw: str | None = None
    status: AuctionStatus = AuctionStatus.UNKNOWN
    image_urls: tuple[HttpUrl, ...] = ()
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("closing_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("datetime must include a timezone")
        return value

    @field_validator("canonical_source_url")
    @classmethod
    def require_canonical_source_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and canonicalize_source_url(str(value)) != str(value):
            raise ValueError("canonical source URL must be session-free and normalized")
        return value

    @field_validator("image_urls")
    @classmethod
    def require_normalized_image_urls(cls, value: tuple[HttpUrl, ...]) -> tuple[HttpUrl, ...]:
        return _require_normalized_image_urls(value)


class AuctionItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    canonical_source_url: HttpUrl
    title: str
    description: str | None = None
    category_raw: str | None = None
    category_canonical: str | None = None
    location_raw: str | None = None
    location_canonical: str | None = None
    location_qualifier: str | None = None
    current_bid: Decimal | None = Field(default=None, ge=0)
    minimum_bid: Decimal | None = Field(default=None, ge=0)
    starting_bid: Decimal | None = Field(default=None, ge=0)
    bid_count: int | None = Field(default=None, ge=0)
    closing_at: datetime | None = None
    status_raw: str | None = None
    status: AuctionStatus = AuctionStatus.UNKNOWN
    image_urls: tuple[HttpUrl, ...] = ()
    first_seen_at: datetime
    last_seen_at: datetime
    last_changed_at: datetime
    scraped_at: datetime
    raw_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: str

    @field_validator(
        "first_seen_at",
        "last_seen_at",
        "last_changed_at",
        "scraped_at",
        "closing_at",
    )
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("datetime must include a timezone")
        return value

    @field_validator("canonical_source_url")
    @classmethod
    def require_canonical_source_url(cls, value: HttpUrl) -> HttpUrl:
        if canonicalize_source_url(str(value)) != str(value):
            raise ValueError("canonical source URL must be session-free and normalized")
        return value

    @field_validator("image_urls")
    @classmethod
    def require_normalized_image_urls(cls, value: tuple[HttpUrl, ...]) -> tuple[HttpUrl, ...]:
        return _require_normalized_image_urls(value)


def _require_normalized_image_urls(value: tuple[HttpUrl, ...]) -> tuple[HttpUrl, ...]:
    if any(normalize_public_url(str(image_url)) != str(image_url) for image_url in value):
        raise ValueError("image URLs must be session-free and normalized")
    return value
