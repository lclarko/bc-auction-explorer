import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ListingBrowserPage } from "./ListingBrowserPage";

function renderPage(initialEntry = "/"): void {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ListingBrowserPage />
        <RouterLocation />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function RouterLocation() {
  const location = useLocation();
  return <output data-testid="router-location">{location.search}</output>;
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

const secondActiveListing = {
  ...listing,
  source_id: "ACTIVE-456",
  title: "Second active listing",
};

const facetsByView = {
  active: {
    categories: [{ value: "Office", count: 1 }],
    locations: [{ value: "Victoria", count: 1 }],
  },
  all: {
    categories: [{ value: "Office", count: 2 }],
    locations: [{ value: "Victoria", count: 2 }],
  },
  ended: {
    categories: [{ value: "Office", count: 1 }],
    locations: [{ value: "Victoria", count: 1 }],
  },
};

function facetsForView(view: string | null) {
  return view === "ended" ? facetsByView.ended : view === "all" ? facetsByView.all : facetsByView.active;
}

let activeListing = listing;
let additionalActiveListings: Array<typeof listing> = [];
let listingRequestUrls: URL[] = [];
let locationRequestUrls: URL[] = [];
let categoryRequestUrls: URL[] = [];
let pendingKeywordResponse: ((response: Response) => void) | undefined;
let delayInitialListingsResponse = false;
let pendingInitialListingsResponse: ((response: Response) => void) | undefined;

function setVisibility(visibilityState: DocumentVisibilityState): void {
  Object.defineProperty(document, "visibilityState", { configurable: true, value: visibilityState });
}

function activeListingBeforeClosing(): typeof listing {
  return {
    ...listing,
    closing_at: "2026-07-15T19:01:00Z",
    first_seen_at: "2026-07-15T18:00:00Z",
    last_changed_at: "2026-07-15T18:00:00Z",
    last_seen_at: "2026-07-15T18:00:00Z",
    observed_at: "2026-07-15T18:00:00Z",
  };
}

beforeEach(() => {
  activeListing = listing;
  additionalActiveListings = [];
  listingRequestUrls = [];
  locationRequestUrls = [];
  categoryRequestUrls = [];
  pendingKeywordResponse = undefined;
  delayInitialListingsResponse = false;
  pendingInitialListingsResponse = undefined;
  setVisibility("visible");
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      if (url.pathname === "/api/listings") {
        listingRequestUrls.push(url);
        if (delayInitialListingsResponse) {
          delayInitialListingsResponse = false;
          return new Promise<Response>((resolve) => {
            pendingInitialListingsResponse = resolve;
          });
        }
        if (url.searchParams.get("keyword") === "updating") {
          return new Promise<Response>((resolve) => {
            pendingKeywordResponse = resolve;
          });
        }
        const page = Number(url.searchParams.get("page") ?? "1");
        const view = url.searchParams.get("view") ?? "active";
        const activeItems = [activeListing, ...additionalActiveListings];
        const dataset =
          view === "ended"
            ? [endedOpenListing]
            : view === "all"
              ? [...activeItems, endedOpenListing]
              : activeItems;
        const pageSize = Number(url.searchParams.get("page_size") ?? "25");
        const totalPages = Math.ceil(dataset.length / pageSize);
        const offset = (page - 1) * pageSize;
        const items = page > totalPages ? [] : dataset.slice(offset, offset + pageSize);
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items,
              page_info: {
                page,
                page_size: pageSize,
                total_items: dataset.length,
                total_pages: totalPages,
              },
            }),
            { headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.pathname === "/api/locations") {
        locationRequestUrls.push(url);
        const facets = facetsForView(url.searchParams.get("view"));
        return Promise.resolve(
          new Response(JSON.stringify({ items: facets.locations }), {
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.pathname === "/api/categories") {
        categoryRequestUrls.push(url);
        const facets = facetsForView(url.searchParams.get("view"));
        return Promise.resolve(
          new Response(JSON.stringify({ items: facets.categories }), {
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
    expect(await screen.findByRole("option", { name: "Victoria (1)" })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Office (1)" })).toBeInTheDocument();
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

  it("uses canonical search state in detail links", async () => {
    renderPage("/?keyword=chair&sessionID=private");

    const detailLink = await screen.findByRole("link", { name: "View details" });
    expect(detailLink).toHaveAttribute(
      "href",
      "/listings/ABC-123?from=keyword%3Dchair",
    );
    expect(detailLink.getAttribute("href")).not.toContain("sessionID");
    expect(detailLink.getAttribute("href")).not.toContain("private");

    await waitFor(() => {
      expect(locationRequestUrls).not.toHaveLength(0);
      expect(categoryRequestUrls).not.toHaveLength(0);
    });
    for (const url of [...listingRequestUrls, ...locationRequestUrls, ...categoryRequestUrls]) {
      expect(url.toString()).not.toContain("sessionID");
      expect(url.toString()).not.toContain("private");
    }
  });

  it("applies Show through the form, resets the page, and scopes facet requests", async () => {
    const user = userEvent.setup();
    additionalActiveListings = Array.from({ length: 25 }, (_, index) => ({
      ...secondActiveListing,
      source_id: `ACTIVE-${index + 1}`,
      title: `Active listing ${index + 1}`,
    }));
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
    expect(await screen.findByRole("option", { name: "Victoria (1)" })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Office (1)" })).toBeInTheDocument();
  });

  it("uses the ended default sort without adding it to the URL", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.selectOptions(await screen.findByRole("combobox", { name: "Show" }), "ended");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => {
      expect(listingRequestUrls.at(-1)?.searchParams.get("sort")).toBe("closing_latest");
      expect(
        new URLSearchParams(screen.getByTestId("router-location").textContent ?? "").has("sort"),
      ).toBe(false);
    });
  });

  it("renders active and ended datasets together in the All view", async () => {
    renderPage("/?view=all");

    expect(await screen.findByRole("heading", { name: "Surplus office chair" })).toBeInTheDocument();
    expect(screen.getByText("2 listings")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Passed closing office chair" })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Victoria (2)" })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Office (2)" })).toBeInTheDocument();
  });

  it.each([
    ["active", "1"],
    ["ended", "1"],
    ["all", "1"],
  ])(
    "returns an out-of-range %s page to its last valid page",
    async (view, expectedPage) => {
      renderPage(`/?view=${view}&page=99`);

      await waitFor(() => {
        expect(listingRequestUrls.length).toBeGreaterThanOrEqual(2);
      });
      expect(listingRequestUrls[0]?.searchParams.get("view")).toBe(view);
      expect(listingRequestUrls[0]?.searchParams.get("page")).toBe("99");
      expect(listingRequestUrls.at(-1)?.searchParams.get("view")).toBe(view);
      expect(listingRequestUrls.at(-1)?.searchParams.get("page")).toBe(expectedPage);
    },
  );

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
    activeListing = activeListingBeforeClosing();
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

  it("detects a closing boundary when initial listings arrive after the minute tick", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-07-15T19:00:00Z"));
    activeListing = activeListingBeforeClosing();
    delayInitialListingsResponse = true;
    renderPage();

    await waitFor(() => expect(pendingInitialListingsResponse).toBeDefined());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    if (!pendingInitialListingsResponse) {
      throw new Error("Expected the initial listings request to be pending.");
    }
    pendingInitialListingsResponse(
      new Response(
        JSON.stringify({
          items: [activeListing],
          page_info: { page: 1, page_size: 25, total_items: 1, total_pages: 1 },
        }),
        { headers: { "Content-Type": "application/json" } },
      ),
    );

    expect(await screen.findByRole("heading", { name: "Surplus office chair" })).toBeInTheDocument();
    expect(
      screen.getByText("Some active listings have reached their scheduled closing time."),
    ).toBeInTheDocument();
  });

  it("refetches listings and view-scoped facets on focus only after a hidden active item crosses", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-07-15T19:00:00Z"));
    activeListing = activeListingBeforeClosing();
    renderPage();

    expect(await screen.findByRole("heading", { name: "Surplus office chair" })).toBeInTheDocument();
    const listingsBeforeFocus = listingRequestUrls.length;
    const locationsBeforeFocus = locationRequestUrls.length;
    const categoriesBeforeFocus = categoryRequestUrls.length;

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });
    expect(listingRequestUrls).toHaveLength(listingsBeforeFocus);
    expect(locationRequestUrls).toHaveLength(locationsBeforeFocus);
    expect(categoryRequestUrls).toHaveLength(categoriesBeforeFocus);

    setVisibility("hidden");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(listingRequestUrls).toHaveLength(listingsBeforeFocus);

    setVisibility("visible");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });

    expect(listingRequestUrls.length).toBeGreaterThan(listingsBeforeFocus);
    expect(locationRequestUrls.length).toBeGreaterThan(locationsBeforeFocus);
    expect(categoryRequestUrls.length).toBeGreaterThan(categoriesBeforeFocus);
  });
});
