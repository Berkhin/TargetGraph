import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import "./index.css";
import App from "./App.tsx";
import { Toaster } from "@/components/ui/sonner";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // staleTime strategy:
      //   - Default 30s for most queries (revalidate frequently as server state changes)
      //   - Can be overridden per hook for stable data (e.g., profiles: 5m)
      //   - Jobs use default: new matches/applicants arrive constantly
      //   - Profiles use 5m: user-driven updates, not server-pushed changes
      staleTime: 30_000,
      // Don't retry client errors (4xx) — a 404/422 won't fix itself.
      retry: (failureCount, error) => {
        const status = isAxiosError(error) ? error.response?.status : undefined;
        if (status !== undefined && status >= 400 && status < 500) return false;
        return failureCount < 2;
      },
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
      <Toaster richColors />
    </QueryClientProvider>
  </StrictMode>,
);
