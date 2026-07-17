import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ListingBrowserPage, ListingNotFound } from "./pages/ListingBrowserPage";
import { ListingDetailPage } from "./pages/ListingDetailPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppShell>
          <Routes>
            <Route element={<ListingBrowserPage />} path="/" />
            <Route element={<ListingDetailPage />} path="/listings/:sourceId" />
            <Route element={<ListingNotFound />} path="*" />
          </Routes>
        </AppShell>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
