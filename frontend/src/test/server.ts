import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import type { FacetList, ListingDetail, ListingPage, ListingSummary, ScrapeStatus } from "../api/client";

const listing = {
  availability: "active",
  bid_count: 0,
  canonical_source_url: "https://www.bcauction.ca/open?id=ABC-123",
  closing_at: "2026-07-20T19:00:00Z",
  complete_absence_count: 0,
  current_bid: "0.00",
  first_seen_at: "2026-07-16T19:00:00Z",
  image_urls: [],
  inventory_state: "current" as const,
  last_changed_at: "2026-07-16T19:00:00Z",
  last_complete_seen_at: "2026-07-16T19:00:00Z",
  last_seen_at: "2026-07-16T19:00:00Z",
  location: "Victoria",
  minimum_bid: "0.00",
  observed_at: "2026-07-16T19:00:00Z",
  source_id: "ABC-123",
  status: "open" as const,
  title: "Surplus office chair",
} satisfies ListingSummary;

const listingPage = {
  items: [listing],
  page_info: { page: 1, page_size: 25, total_items: 1, total_pages: 1 },
} satisfies ListingPage;

const locations = { items: [{ value: "Victoria", count: 1 }] } satisfies FacetList;
const categories = { items: [{ value: "Office", count: 1 }] } satisfies FacetList;
const latestCompleteRun = {
  completion_status: "complete" as const,
  detail_attempted: 1,
  detail_succeeded: 1,
  duplicate_listings_enumerated: 0,
  enumeration_complete: true,
  expected_product_groups: 1,
  finished_at: "2026-07-16T19:05:00Z",
  item_failures: 0,
  items_created: 1,
  items_seen: 1,
  items_updated: 0,
  mode: "detail",
  observations_created: 1,
  pages_visited: 1,
  persistence_failures: 0,
  persistence_succeeded: 1,
  processed_product_groups: 1,
  rate_limit_responses: 0,
  requested_limit: 20,
  source_request_duration_ms: 100,
  source_request_wait_duration_ms: 50,
  source_requests: 2,
  source_responses: 2,
  source_retries: 0,
  source_retry_wait_duration_ms: 0,
  source_transport_errors: 0,
  started_at: "2026-07-16T19:00:00Z",
  status: "succeeded" as const,
  unique_listings_enumerated: 1,
};
const scrapeStatus = {
  active_listing_count: 1,
  latest_complete_age_seconds: 60,
  latest_complete_run: latestCompleteRun,
  latest_listing_seen_at: "2026-07-16T19:00:00Z",
  latest_run: null,
  latest_successful_run: latestCompleteRun,
  listing_count: 1,
  stale_listing_count: 0,
} satisfies ScrapeStatus;
const listingDetail = {
  ...listing,
  category: "Office",
  category_canonical: null,
  category_raw: "Office",
  description: "A clean surplus chair.",
  location_canonical: "Victoria",
  location_normalization_status: "exact",
  location_qualifier: null,
  location_raw: "Victoria",
  pickup_details: "Arrange pickup with the contact named on the source listing.",
  starting_bid: null,
  status_raw: "Open",
} satisfies ListingDetail;

export const server = setupServer(
  http.get(/\/api\/listings(?:\?.*)?$/, () => HttpResponse.json(listingPage)),
  http.get(/\/api\/locations(?:\?.*)?$/, () => HttpResponse.json(locations)),
  http.get(/\/api\/categories(?:\?.*)?$/, () => HttpResponse.json(categories)),
  http.get(/\/api\/scrape-status(?:\?.*)?$/, () => HttpResponse.json(scrapeStatus)),
  http.get(/\/api\/listings\/.+(?:\?.*)?$/, () => HttpResponse.json(listingDetail)),
);
