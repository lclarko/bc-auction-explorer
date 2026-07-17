import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ListingBrowserPage } from "./ListingBrowserPage";

function renderPage(initialEntry = "/"): void {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ListingBrowserPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

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
  status: "open",
  title: "Surplus office chair",
};

let listingRequestUrls: URL[] = [];
let pendingKeywordResponse: ((response: Response) => void) | undefined;

beforeEach(() => {
  listingRequestUrls = [];
  pendingKeywordResponse = undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      if (url.pathname === "/api/listings") {
        listingRequestUrls.push(url);
        if (url.searchParams.get("keyword") === "updating") {
          return new Promise<Response>((resolve) => {
            pendingKeywordResponse = resolve;
          });
        }
        const page = Number(url.searchParams.get("page") ?? "1");
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: page === 2 ? [] : [listing],
              page_info: {
                page,
                page_size: 25,
                total_items: page === 2 ? 0 : 1,
                total_pages: page === 2 ? 0 : 1,
              },
            }),
            { headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.pathname === "/api/locations") {
        return Promise.resolve(
          new Response(JSON.stringify({ items: [{ value: "Victoria", count: 1 }] }), {
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.pathname === "/api/categories") {
        return Promise.resolve(
          new Response(JSON.stringify({ items: [{ value: "Office", count: 1 }] }), {
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ error: { code: "not_found", message: "Not found" } }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

describe("ListingBrowserPage", () => {
  it("renders an API listing and its real zero bid", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Surplus office chair" })).toBeInTheDocument();
    expect(screen.getByText("$0.00")).toBeInTheDocument();
    expect(screen.getByText("0 bids")).toBeInTheDocument();
  });

  it("applies a keyword through the search form", async () => {
    const user = userEvent.setup();
    renderPage();

    const input = await screen.findByRole("searchbox", { name: "Keyword" });
    await user.type(input, "chair");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => {
      expect(listingRequestUrls.at(-1)?.searchParams.get("keyword")).toBe("chair");
    });
    expect(await screen.findByRole("heading", { name: "Surplus office chair" })).toBeInTheDocument();
  });

  it("returns an out-of-range empty page to the first page", async () => {
    renderPage("/?page=2");

    await waitFor(() => {
      expect(listingRequestUrls.length).toBeGreaterThanOrEqual(2);
    });
    expect(listingRequestUrls[0]?.searchParams.get("page")).toBe("2");
    expect(listingRequestUrls.at(-1)?.searchParams.get("page")).toBe("1");
  });

  it("announces an update instead of a stale result count", async () => {
    const user = userEvent.setup();
    renderPage();

    const input = await screen.findByRole("searchbox", { name: "Keyword" });
    await user.type(input, "updating");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));

    expect(await screen.findByText("Updating listings")).toBeInTheDocument();
    expect(screen.queryByText("1 listing")).not.toBeInTheDocument();

    if (!pendingKeywordResponse) {
      throw new Error("Expected the filtered listings request to be pending.");
    }
    pendingKeywordResponse(
      new Response(
        JSON.stringify({
          items: [listing],
          page_info: { page: 1, page_size: 25, total_items: 1, total_pages: 1 },
        }),
        { headers: { "Content-Type": "application/json" } },
      ),
    );
    expect(await screen.findByText("1 listing")).toBeInTheDocument();
  });
});
