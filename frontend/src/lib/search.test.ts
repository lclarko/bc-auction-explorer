import { describe, expect, it } from "vitest";

import { currency } from "./format";
import {
  effectiveListingSort,
  listingQuery,
  listingSearchParams,
  parseListingSearch,
  withFirstPage,
} from "./search";
import { dateInputToUtc } from "./time";

describe("listing search state", () => {
  it("keeps the default active view and its closing-soon sort out of the URL", () => {
    const search = parseListingSearch(new URLSearchParams());

    expect(search.view).toBe("active");
    expect(search.sort).toBeNull();
    expect(effectiveListingSort(search)).toBe("closing_soon");
    expect(listingSearchParams(search).toString()).toBe("");
  });

  it("uses view-specific defaults while preserving an explicit sort", () => {
    const ended = parseListingSearch(new URLSearchParams("view=ended"));
    const endedWithExplicitDefault = parseListingSearch(
      new URLSearchParams("view=ended&sort=closing_latest"),
    );
    const all = parseListingSearch(new URLSearchParams("view=all&sort=price_high&page=3"));

    expect(ended.sort).toBeNull();
    expect(effectiveListingSort(ended)).toBe("closing_latest");
    expect(listingSearchParams(ended).toString()).toBe("view=ended");
    expect(endedWithExplicitDefault.sort).toBe("closing_latest");
    expect(listingSearchParams(endedWithExplicitDefault).toString()).toBe(
      "view=ended&sort=closing_latest",
    );
    expect(effectiveListingSort(all)).toBe("price_high");
    expect(listingSearchParams(withFirstPage(all)).toString()).toBe("view=all&sort=price_high");
  });

  it("preserves a zero price and converts Pacific date bounds to UTC", () => {
    const search = parseListingSearch(
      new URLSearchParams("min_price=0&closing_after=2026-03-08&closing_before=2026-11-01"),
    );
    const query = listingQuery(search);

    expect(query.min_price).toBe("0");
    expect(query.closing_after).toBe("2026-03-08T08:00:00.000Z");
    // B.C. remains on UTC-7 after its final spring-forward transition in 2026.
    expect(query.closing_before).toBe("2026-11-02T06:59:59.999Z");
    expect(query.view).toBe("active");
    expect(query.sort).toBe("closing_soon");
  });

  it("rejects invalid URL values", () => {
    const search = parseListingSearch(
      new URLSearchParams(
        "view=not-a-view&sort=surprise&page=0&min_price=-1&closing_after=2026-02-30",
      ),
    );

    expect(search).toMatchObject({
      closingAfter: "",
      minPrice: "",
      page: 1,
      sort: null,
      view: "active",
    });
  });

  it("keeps free-text filters within the API limit", () => {
    const atLimit = "a".repeat(200);
    const beyondLimit = "b".repeat(201);
    const search = parseListingSearch(
      new URLSearchParams({
        category: beyondLimit,
        keyword: atLimit,
        location: beyondLimit,
      }),
    );

    expect(search.keyword).toBe(atLimit);
    expect(search.location).toBe("");
    expect(search.category).toBe("");
  });
});

describe("display formatting", () => {
  it("distinguishes a zero bid from an unavailable bid", () => {
    expect(currency("0.00")).toBe("$0.00");
    expect(currency(null)).toBe("Not available");
  });

  it("creates end-of-day Pacific bounds", () => {
    expect(dateInputToUtc("2026-07-16", "end")).toBe("2026-07-17T06:59:59.999Z");
  });
});
