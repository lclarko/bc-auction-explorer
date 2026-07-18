import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
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
  availability: "active",
  bid_count: 0,
  canonical_source_url: "https://www.bcauction.ca/open?id=ABC-123",
  closing_at: "2099-07-20T19:00:00Z",
  current_bid: "0.00",
  first_seen_at: "2026-07-16T19:00:00Z",
  image_urls: [],
  last_changed_at: "2026-07-16T19:00:00Z",
  last_seen_at: "2026-07-16T19:00:00Z",
  location: "Victoria",
  minimum_bid: "0.00",
  observed_at: "2026-07-16T19:00:00Z",
  source_id: "ABC-123",
  status: "open",
  title: "Surplus office chair",
};

const endedOpenListing = {
  ...listing,
  availability: "scheduled_closing_passed",
  closing_at: "2026-07-15T19:00:00Z",
  observed_at: "2026-07-15T18:00:00Z",
  source_id: "ENDED-123",
  title: "Passed closing office chair",
};

let activeListing = listing;
let listingRequestUrls: URL[] = [];
let locationRequestUrls: URL[] = [];
let categoryRequestUrls: URL[] = [];
let pendingKeywordResponse: ((response: Response) => void) | undefined;

function setVisibility(visibilityState: DocumentVisibilityState): void {
  Object.defineProperty(document, "visibilityState", { configurable: true, value: visibilityState });
}

beforeEach(() => {
  activeListing = listing;
  listingRequestUrls = [];
  locationRequestUrls = [];
  categoryRequestUrls = [];
  pendingKeywordResponse = undefined;
  setVisibility("visible");
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
        const view = url.searchParams.get("view") ?? "active";
        const items = view === "ended" ? [endedOpenListing] : page === 2 ? [] : [activeListing];
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items,
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
        locationRequestUrls.push(url);
        return Promise.resolve(
          new Response(JSON.stringify({ items: [{ value: "Victoria", count: 1 }] }), {
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.pathname === "/api/categories") {
        categoryRequestUrls.push(url);
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

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  setVisibility("visible");
});

describe("ListingBrowserPage", () => {
  it("renders an active API listing and its real zero bid", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Surplus office chair" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Browse active auction listings" })).toBeInTheDocument();
    expect(screen.getByText("$0.00")).toBeInTheDocument();
    expect(screen.getByText("0 bids")).toBeInTheDocument();
    expect(listingRequestUrls.at(-1)?.searchParams.get("view")).toBe("active");
  });

  it("applies a keyword through the existing filter form", async () => {
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

  it("applies Show through the form, resets the page, and scopes facet requests", async () => {
    const user = userEvent.setup();
    renderPage("/?page=2&sort=price_high");

    const show = await screen.findByRole("combobox", { name: "Show" });
    await user.selectOptions(show, "ended");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => {
      expect(listingRequestUrls.at(-1)?.searchParams.get("view")).toBe("ended");
      expect(listingRequestUrls.at(-1)?.searchParams.get("page")).toBe("1");
      expect(listingRequestUrls.at(-1)?.searchParams.get("sort")).toBe("price_high");
    });
    await waitFor(() => {
      expect(locationRequestUrls.at(-1)?.searchParams.get("view")).toBe("ended");
      expect(categoryRequestUrls.at(-1)?.searchParams.get("view")).toBe("ended");
    });
    expect(
      await screen.findByRole("heading", { name: "Browse ended auction listings" }),
    ).toBeInTheDocument();
  });

  it("uses the ended default sort without adding it to the URL", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.selectOptions(await screen.findByRole("combobox", { name: "Show" }), "ended");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => {
      expect(listingRequestUrls.at(-1)?.searchParams.get("sort")).toBe("closing_latest");
    });
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
          items: [activeListing],
          page_info: { page: 1, page_size: 25, total_items: 1, total_pages: 1 },
        }),
        { headers: { "Content-Type": "application/json" } },
      ),
    );
    expect(await screen.findByText("1 listing")).toBeInTheDocument();
  });

  it("keeps the source Open badge and shows when it was last observed after closing", async () => {
    renderPage("/?view=ended");

    expect(await screen.findByRole("heading", { name: "Passed closing office chair" })).toBeInTheDocument();
    expect(screen.getByText("Open", { selector: ".status-badge" })).toBeInTheDocument();
    expect(screen.getByText(/Scheduled closing time passed .* Last observed open at/)).toBeInTheDocument();
  });

  it("keeps an active card stable and offers a refresh after its closing boundary", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-07-15T19:00:00Z"));
    activeListing = { ...listing, closing_at: "2026-07-15T19:01:00Z" };
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderPage();

    expect(await screen.findByRole("heading", { name: "Surplus office chair" })).toBeInTheDocument();
    const listingsBeforeBoundary = listingRequestUrls.length;
    const locationsBeforeBoundary = locationRequestUrls.length;
    const categoriesBeforeBoundary = categoryRequestUrls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(listingRequestUrls).toHaveLength(listingsBeforeBoundary);
    expect(locationRequestUrls).toHaveLength(locationsBeforeBoundary);
    expect(categoryRequestUrls).toHaveLength(categoriesBeforeBoundary);
    expect(screen.getByRole("heading", { name: "Surplus office chair" })).toBeInTheDocument();
    expect(screen.getByText(/Scheduled closing time passed .* Last observed open at/)).toBeInTheDocument();
    expect(
      screen.getByText("Some active listings have reached their scheduled closing time."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Refresh results" }));

    expect(listingRequestUrls.length).toBeGreaterThan(listingsBeforeBoundary);
    expect(locationRequestUrls.length).toBeGreaterThan(locationsBeforeBoundary);
    expect(categoryRequestUrls.length).toBeGreaterThan(categoriesBeforeBoundary);
  });

  it("refetches listings and view-scoped facets on focus only after a hidden active item crosses", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-07-15T19:00:00Z"));
    activeListing = { ...listing, closing_at: "2026-07-15T19:01:00Z" };
    renderPage();

    expect(await screen.findByRole("heading", { name: "Surplus office chair" })).toBeInTheDocument();
    const listingsBeforeFocus = listingRequestUrls.length;
    const locationsBeforeFocus = locationRequestUrls.length;
    const categoriesBeforeFocus = categoryRequestUrls.length;

    setVisibility("hidden");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(listingRequestUrls).toHaveLength(listingsBeforeFocus);

    setVisibility("visible");
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });

    expect(listingRequestUrls.length).toBeGreaterThan(listingsBeforeFocus);
    expect(locationRequestUrls.length).toBeGreaterThan(locationsBeforeFocus);
    expect(categoryRequestUrls.length).toBeGreaterThan(categoriesBeforeFocus);
  });
});
