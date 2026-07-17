import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell";

afterEach(() => vi.unstubAllGlobals());

describe("AppShell", () => {
  it("does not show an empty scrape state while the status request is loading", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AppShell>Content</AppShell>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("Loading refresh status.")).toBeInTheDocument();
    expect(screen.queryByText("No scrape run has been recorded yet.")).not.toBeInTheDocument();
  });
});
