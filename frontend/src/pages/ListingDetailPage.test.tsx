import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ListingDetailPage } from "./ListingDetailPage";

const detail = {
  availability: "active",
  bid_count: 2,
  canonical_source_url: "https://www.bcauction.ca/open?id=ABC-123",
  category: "Office",
  category_canonical: null,
  category_raw: "Office",
  closing_at: "2026-07-20T19:00:00Z",
  current_bid: "25.00",
  description: "A clean surplus chair.",
  first_seen_at: "2026-07-16T19:00:00Z",
  image_urls: [],
  last_changed_at: "2026-07-16T19:00:00Z",
  last_seen_at: "2026-07-16T19:00:00Z",
  location: "Victoria",
  location_canonical: "Victoria",
  location_normalization_status: "exact",
  location_qualifier: null,
  location_raw: "Victoria",
  minimum_bid: "10.00",
  observed_at: "2026-07-16T19:00:00Z",
  pickup_details: null,
  source_id: "ABC-123",
  starting_bid: null,
  status: "open",
  status_raw: "Open",
  title: "Surplus office chair",
};

function renderDetail(): void {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/listings/ABC-123"]}>
        <Routes>
          <Route element={<ListingDetailPage />} path="/listings/:sourceId" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("ListingDetailPage", () => {
  it("retries a recoverable detail request", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ error: { code: "unavailable", message: "Try again shortly." } }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(detail), { headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();

    renderDetail();

    expect(await screen.findByRole("heading", { name: "Listing is unavailable" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Surplus office chair" })).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("keeps a scheduled closing pass distinct from the source Open status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              ...detail,
              availability: "scheduled_closing_passed",
              closing_at: "2026-07-15T19:00:00Z",
              observed_at: "2026-07-15T18:00:00Z",
            }),
            { headers: { "Content-Type": "application/json" } },
          ),
        ),
      ),
    );

    renderDetail();

    expect(await screen.findByRole("heading", { name: "Surplus office chair" })).toBeInTheDocument();
    expect(screen.getByText("Open", { selector: ".status-badge" })).toBeInTheDocument();
    expect(screen.getByText(/Scheduled closing time passed .* Last observed open at/)).toBeInTheDocument();
  });
});
