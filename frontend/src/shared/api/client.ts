import axios from "axios";

// Shared axios instance for the FastAPI backend.
// Defaults to a same-origin relative path so requests flow through the Nginx
// reverse proxy (prod) or the Vite dev proxy (local) — no host/IP baked in.
// Override with an absolute VITE_API_BASE_URL only to hit a remote backend.
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api/v1",
  headers: {
    "Content-Type": "application/json",
  },
});
