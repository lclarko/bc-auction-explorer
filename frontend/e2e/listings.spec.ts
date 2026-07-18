import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const activeListing = {
  availability: "active",
  bid_count: 1,
  canonical_source_url: "https://www.bcauction.ca/open?id=ACTIVE-001",
  closing_at: "2099-12-20T19:00:00Z",
  current_bid: "10.00",
  first_seen_at: "2026-07-16T19:00:00Z",
  image_urls: [],
  last_changed_at: "2026-07-16T19:00:00Z",
  last_seen_at: "2026-07-16T19:00:00Z",
  location: "Victoria",
  minimum_bid: "0.00",
  observed_at: "2026-07-16T19:00:00Z",
  source_id: "ACTIVE-001",
  status: "open",
  title: "Active office chair",
};

const passedOpenListing = {
  availability: "scheduled_closing_passed",
  bid_count: 0,
  canonical_source_url: "https://www.bcauction.ca/open?id=OPEN-123",
  closing_at: "2000-01-20T19:00:00Z",
  current_bid: "0.00",
  first_seen_at: "2026-07-16T19:00:00Z",
  image_urls: [],
  last_changed_at: "2026-07-16T19:00:00Z",
  last_seen_at: "2026-07-16T19:00:00Z",
  location: "Victoria",
  minimum_bid: "0.00",
  observed_at: "2026-07-16T19:00:00Z",
  source_id: "OPEN-123",
  status: "open",
  title: "Chair with passed closing time",
};

const confirmedClosedListing = {
  availability: "closed",
  bid_count: 3,
  canonical_source_url: "https://www.bcauction.ca/open?id=CLOSED-456",
  closed_at: "2026-07-16T20:00:00Z",
  closing_at: "2000-01-21T19:00:00Z",
  current_bid: "25.00",
  first_seen_at: "2026-07-16T19:00:00Z",
  image_urls: [],
  last_changed_at: "2026-07-16T20:00:00Z",
  last_seen_at: "2026-07-16T20:00:00Z",
  location: "Surrey",
  minimum_bid: "0.00",
  observed_at: "2026-07-16T20:00:00Z",
  source_id: "CLOSED-456",
  status: "closed",
  title: "Confirmed closed chair",
};

function listingsForView(view: string, page: number): object {
  if (view === "ended") {
    return {
      items: [passedOpenListing, confirmedClosedListing],
      page_info: { page: 1, page_size: 2, total_items: 2, total_pages: 1 },
    };
  }
  if (view === "all") {
    return {
      items:
        page === 3 ? [confirmedClosedListing] : page === 2 ? [passedOpenListing] : [activeListing],
      page_info: { page, page_size: 1, total_items: 3, total_pages: 3 },
    };
  }
  return {
    items: [activeListing],
    page_info: { page: 1, page_size: 1, total_items: 1, total_pages: 1 },
  };
}

function locationFacetsForView(view: string): object {
  if (view === "ended") {
    return {
      items: [
        { value: "Surrey", count: 1 },
        { value: "Victoria", count: 1 },
      ],
    };
  }
  if (view === "all") {
    return {
      items: [
        { value: "Surrey", count: 1 },
        { value: "Victoria", count: 2 },
      ],
    };
  }
  return { items: [{ value: "Victoria", count: 1 }] };
}

function categoryFacetsForView(view: string): object {
  if (view === "ended") {
    return { items: [{ value: "Office furniture", count: 2 }] };
  }
  if (view === "all") {
    return { items: [{ value: "Office furniture", count: 3 }] };
  }
  return { items: [{ value: "Office furniture", count: 1 }] };
}

async function mockApi(
  page: Page,
): Promise<{ listing: URL[]; locations: URL[]; categories: URL[] }> {
  const requestUrls = { categories: [] as URL[], listing: [] as URL[], locations: [] as URL[] };
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const respond = (body: object, status = 200): Promise<void> =>
      route.fulfill({ body: JSON.stringify(body), contentType: "application/json", status });

    if (url.pathname === "/api/listings") {
      requestUrls.listing.push(url);
      const requestedPage = Number(url.searchParams.get("page") ?? "1");
      const view = url.searchParams.get("view") ?? "active";
      await respond(listingsForView(view, requestedPage));
      return;
    }
    if (url.pathname === "/api/locations") {
      requestUrls.locations.push(url);
      await respond(locationFacetsForView(url.searchParams.get("view") ?? "active"));
      return;
    }
    if (url.pathname === "/api/categories") {
      requestUrls.categories.push(url);
      await respond(categoryFacetsForView(url.searchParams.get("view") ?? "active"));
      return;
    }
    if (url.pathname === "/api/scrape-status") {
      await respond({
        latest_listing_seen_at: confirmedClosedListing.last_seen_at,
        latest_run: null,
        latest_successful_run: null,
        listing_count: 3,
      });
      return;
    }
    if (
      url.pathname === "/api/listings/ACTIVE-001" ||
      url.pathname === "/api/listings/OPEN-123" ||
      url.pathname === "/api/listings/CLOSED-456"
    ) {
      const listing = url.pathname.endsWith("CLOSED-456")
        ? confirmedClosedListing
        : url.pathname.endsWith("OPEN-123")
          ? passedOpenListing
          : activeListing;
      await respond({
        ...listing,
        category: "Office furniture",
        category_canonical: null,
        category_raw: "Office furniture",
        description: "A public auction listing.",
        location_canonical: listing.location,
        location_normalization_status: "exact",
        location_qualifier: null,
        location_raw: listing.location,
        pickup_details: "Arrange pickup with the contact named on the source listing.",
        starting_bid: null,
        status_raw: listing.status === "closed" ? "Closed" : "Open",
      });
      return;
    }
    await respond({ error: { code: "not_found", message: "Not found" } }, 404);
  });
  return requestUrls;
}

test("browses active, ended, and all auction views", async ({ page }) => {
  const requestUrls = await mockApi(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Browse active auction listings" })).toBeVisible();
  await expect(page.getByText("1 listing")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Active office chair" })).toBeVisible();
  await expect(page.getByText("$10.00")).toBeVisible();
  await expect(page.getByText("Open", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Location")).toContainText("Victoria (1)");
  await expect(page.getByLabel("Category")).toContainText("Office furniture (1)");
  await expect(page).not.toHaveURL(/view=/);

  await page.getByRole("searchbox", { name: "Keyword" }).fill("chair");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/keyword=chair/);

  await page.getByLabel("Show").selectOption({ label: "Ended auctions" });
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/keyword=chair.*view=ended/);
  await expect(page.getByRole("heading", { name: "Browse ended auction listings" })).toBeVisible();
  await expect(page.getByText("2 listings")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Chair with passed closing time" })).toBeVisible();
  await expect(page.getByText("Open", { exact: true })).toBeVisible();
  await expect(page.getByText(/Scheduled closing time passed/)).toBeVisible();
  await expect(page.getByText(/Last observed open at/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Confirmed closed chair" })).toBeVisible();
  await expect(page.getByText("Closed", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Location")).toContainText("Surrey (1)");
  await expect(page.getByLabel("Location")).toContainText("Victoria (1)");
  await expect(page.getByLabel("Category")).toContainText("Office furniture (2)");
  await expect.poll(() => requestUrls.listing.at(-1)?.searchParams.get("view")).toBe("ended");
  await expect.poll(() => requestUrls.locations.at(-1)?.searchParams.get("view")).toBe("ended");
  await expect.poll(() => requestUrls.categories.at(-1)?.searchParams.get("view")).toBe("ended");

  await page.reload();
  await expect(page.getByRole("heading", { name: "Browse ended auction listings" })).toBeVisible();
  await expect(page.getByLabel("Show")).toHaveValue("ended");
  await expect(page.getByRole("searchbox", { name: "Keyword" })).toHaveValue("chair");

  await page.getByLabel("Show").selectOption({ label: "All auctions" });
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/keyword=chair.*view=all/);
  await expect(page.getByRole("heading", { name: "Browse all indexed auction listings" })).toBeVisible();
  await expect(page.getByText("3 listings")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Active office chair" })).toBeVisible();
  await expect(page.getByLabel("Location")).toContainText("Surrey (1)");
  await expect(page.getByLabel("Location")).toContainText("Victoria (2)");
  await expect(page.getByLabel("Category")).toContainText("Office furniture (3)");

  await page.getByRole("button", { name: "Next" }).click();
  await expect(page).toHaveURL(/view=all.*page=2/);
  await expect(page.getByRole("heading", { name: "Chair with passed closing time" })).toBeVisible();
  await expect(page.getByText(/Scheduled closing time passed/)).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page).toHaveURL(/view=all.*page=3/);
  await expect(page.getByRole("heading", { name: "Confirmed closed chair" })).toBeVisible();
  await page.getByRole("button", { name: "Previous" }).click();
  await expect(page).toHaveURL(/view=all.*page=2/);
  await expect(page.getByRole("heading", { name: "Chair with passed closing time" })).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page).toHaveURL(/view=all.*page=3/);
  await expect(page.getByRole("heading", { name: "Confirmed closed chair" })).toBeVisible();
  await expect.poll(() => requestUrls.listing.at(-1)?.searchParams.get("view")).toBe("all");
  await expect.poll(() => requestUrls.listing.at(-1)?.searchParams.get("page")).toBe("3");
  await expect.poll(() => requestUrls.listing.at(-1)?.searchParams.get("keyword")).toBe("chair");

  await page.getByRole("link", { name: "View details" }).click();
  await expect(page.getByRole("heading", { name: "Confirmed closed chair" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Pickup details" })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByRole("link", { name: "Back to listings" }).click();
  await expect(page).toHaveURL(/keyword=chair.*view=all.*page=3/);
  await expect(page.getByRole("heading", { name: "Confirmed closed chair" })).toBeVisible();

  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
