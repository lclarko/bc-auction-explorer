// @vitest-environment node

import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { getListings } from "./client";
import { server } from "../test/server";

describe("typed API client", () => {
  it("reads a listing page through the generated route contract", async () => {
    const page = await getListings({ page: 1, page_size: 25, sort: "closing_soon", status: "open" });

    expect(page.page_info.total_items).toBe(1);
    expect(page.items[0]?.source_id).toBe("ABC-123");
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
