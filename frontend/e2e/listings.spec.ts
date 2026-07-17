import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

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

async function mockApi(page: Page): Promise<URL[]> {
  const listingRequestUrls: URL[] = [];
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const respond = (body: object, status = 200): Promise<void> =>
      route.fulfill({ body: JSON.stringify(body), contentType: "application/json", status });

    if (url.pathname === "/api/listings") {
      listingRequestUrls.push(url);
      await respond({
        items: [listing],
        page_info: { page: 1, page_size: 25, total_items: 1, total_pages: 1 },
      });
      return;
    }
    if (url.pathname === "/api/locations") {
      await respond({ items: [{ value: "Victoria", count: 1 }] });
      return;
    }
    if (url.pathname === "/api/categories") {
      await respond({ items: [{ value: "Office", count: 1 }] });
      return;
    }
    if (url.pathname === "/api/scrape-status") {
      await respond({
        latest_listing_seen_at: listing.last_seen_at,
        latest_run: null,
        latest_successful_run: null,
        listing_count: 1,
      });
      return;
    }
    if (url.pathname === "/api/listings/ABC-123") {
      await respond({
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
      });
      return;
    }
    await respond({ error: { code: "not_found", message: "Not found" } }, 404);
  });
  return listingRequestUrls;
}

test("browses, filters, opens a detail page, and returns to results", async ({ page }) => {
  const listingRequestUrls = await mockApi(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Surplus office chair" })).toBeVisible();
  await expect(page.getByText("$0.00")).toBeVisible();

  await page.getByRole("searchbox", { name: "Keyword" }).fill("chair");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/keyword=chair/);
  await expect.poll(() => listingRequestUrls.at(-1)?.searchParams.get("keyword")).toBe("chair");

  await page.getByRole("link", { name: "View details" }).click();
  await expect(page.getByRole("heading", { name: "Surplus office chair" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Pickup details" })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByRole("link", { name: "Back to listings" }).click();
  await expect(page).toHaveURL(/keyword=chair/);
  await expect(page.getByRole("heading", { name: "Surplus office chair" })).toBeVisible();

  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
