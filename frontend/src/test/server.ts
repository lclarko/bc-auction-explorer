import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

const listing = {
  bid_count: 0,
  canonical_source_url: "https://www.bcauction.ca/open?id=ABC-123",
  closing_at: "2026-07-20T19:00:00Z",
  current_bid: "0.00",
  first_seen_at: "2026-07-16T19:00:00Z",
  image_urls: [],
  last_changed_at: "2026-07-16T19:00:00Z",
  last_seen_at: "2026-07-16T19:00:00Z",
  location: "Victoria",
  minimum_bid: "0.00",
  source_id: "ABC-123",
  status: "open" as const,
  title: "Surplus office chair",
};

export const server = setupServer(
  http.get(/\/api\/listings(?:\?.*)?$/, () =>
    HttpResponse.json({
      items: [listing],
      page_info: { page: 1, page_size: 25, total_items: 1, total_pages: 1 },
    }),
  ),
  http.get(/\/api\/locations(?:\?.*)?$/, () =>
    HttpResponse.json({ items: [{ value: "Victoria", count: 1 }] }),
  ),
  http.get(/\/api\/categories(?:\?.*)?$/, () =>
    HttpResponse.json({ items: [{ value: "Office", count: 1 }] }),
  ),
  http.get(/\/api\/scrape-status(?:\?.*)?$/, () =>
    HttpResponse.json({
      latest_listing_seen_at: "2026-07-16T19:00:00Z",
      latest_run: null,
      latest_successful_run: null,
      listing_count: 1,
    }),
  ),
  http.get(/\/api\/listings\/.+(?:\?.*)?$/, () =>
    HttpResponse.json({
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
    }),
  ),
);
