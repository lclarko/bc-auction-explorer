import { describe, expect, it } from "vitest";

import { listingLifecycleText, pacificDateTime } from "./time";

describe("Pacific time formatting", () => {
  it("uses the exact Pacific daylight and standard abbreviations", () => {
    expect(pacificDateTime("2026-01-15T20:00:00Z")).toBe("Jan 15, 2026, 12:00 p.m. PST");
    expect(pacificDateTime("2026-07-15T19:00:00Z")).toBe("Jul 15, 2026, 12:00 p.m. PDT");
  });
});

describe("listing lifecycle text", () => {
  it("updates active countdown text from the supplied clock", () => {
    const now = Date.parse("2026-07-15T19:00:00Z");

    expect(
      listingLifecycleText("active", "open", "2026-07-15T19:02:00Z", "2026-07-15T18:00:00Z", now),
    ).toBe("Closes in 2 minutes.");
  });

  it("keeps a passed open listing distinct from a source terminal status", () => {
    const now = Date.parse("2026-07-15T19:02:00Z");
    const observedAt = "2026-07-15T18:00:00Z";

    expect(
      listingLifecycleText(
        "scheduled_closing_passed",
        "open",
        "2026-07-15T19:00:00Z",
        observedAt,
        now,
      ),
    ).toBe(`Scheduled closing time passed 2 minutes ago. Last observed open at ${pacificDateTime(observedAt)}.`);
  });

  it("updates an active listing locally when its closing time passes", () => {
    const observedAt = "2026-07-15T18:00:00Z";

    expect(
      listingLifecycleText(
        "active",
        "open",
        "2026-07-15T19:00:00Z",
        observedAt,
        Date.parse("2026-07-15T19:01:00Z"),
      ),
    ).toBe(`Scheduled closing time passed 1 minute ago. Last observed open at ${pacificDateTime(observedAt)}.`);
  });

  it("labels an open listing without a closing time as unavailable", () => {
    expect(listingLifecycleText("unknown", "open", null, "2026-07-15T18:00:00Z")).toBe(
      "Closing time unavailable.",
    );
  });
});
