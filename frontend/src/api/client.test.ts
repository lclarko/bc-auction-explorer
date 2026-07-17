// @vitest-environment node

import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { getListings } from "./client";
import { server } from "../test/server";

describe("typed API client", () => {
  it("reads a listing page through the generated route contract", async () => {
    let requestUrl: URL | undefined;
    server.use(
      http.get(/\/api\/listings(?:\?.*)?$/, ({ request }) => {
        requestUrl = new URL(request.url);
        return HttpResponse.json({
          items: [
            {
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
              status: "open",
              title: "Surplus office chair",
            },
          ],
          page_info: { page: 1, page_size: 25, total_items: 1, total_pages: 1 },
        });
      }),
    );

    const page = await getListings({ page: 1, page_size: 25, sort: "closing_soon", status: "open" });

    expect(page.page_info.total_items).toBe(1);
    expect(page.items[0]?.source_id).toBe("ABC-123");
    expect(requestUrl?.searchParams.get("page")).toBe("1");
    expect(requestUrl?.searchParams.get("page_size")).toBe("25");
    expect(requestUrl?.searchParams.get("sort")).toBe("closing_soon");
    expect(requestUrl?.searchParams.get("status")).toBe("open");
  });

  it("normalizes a structured API error", async () => {
    server.use(
      http.get(/\/api\/listings(?:\?.*)?$/, () =>
        HttpResponse.json(
          { error: { code: "invalid_query", message: "The price range is invalid." } },
          { status: 422 },
        ),
      ),
    );

    await expect(
      getListings({ page: 1, page_size: 25, sort: "closing_soon", status: "open" }),
    ).rejects.toMatchObject({
      code: "invalid_query",
      message: "The price range is invalid.",
      status: 422,
    });
  });
});
