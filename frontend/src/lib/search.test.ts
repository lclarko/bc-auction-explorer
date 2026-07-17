import { describe, expect, it } from "vitest";

import { currency } from "./format";
import { listingQuery, listingSearchParams, parseListingSearch } from "./search";
import { dateInputToUtc } from "./time";

describe("listing search state", () => {
  it("keeps the default open and closing-soon state out of the URL", () => {
    const search = parseListingSearch(new URLSearchParams());

    expect(search.status).toBe("open");
    expect(search.sort).toBe("closing_soon");
    expect(listingSearchParams(search).toString()).toBe("");
  });

  it("preserves a zero price and converts Pacific date bounds to UTC", () => {
    const search = parseListingSearch(
      new URLSearchParams("min_price=0&closing_after=2026-03-08&closing_before=2026-11-01"),
    );
    const query = listingQuery(search);

    expect(query.min_price).toBe("0");
    expect(query.closing_after).toBe("2026-03-08T08:00:00.000Z");
    expect(query.closing_before).toBe("2026-11-02T07:59:59.999Z");
  });

  it("rejects invalid URL values", () => {
    const search = parseListingSearch(
      new URLSearchParams(
        "status=not-a-status&sort=surprise&page=0&min_price=-1&closing_after=2026-02-30",
      ),
    );

    expect(search).toMatchObject({
      closingAfter: "",
      minPrice: "",
      page: 1,
      sort: "closing_soon",
      status: "open",
    });
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
