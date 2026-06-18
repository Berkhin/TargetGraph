import axios from "axios";

// Shared axios instance for the FastAPI backend.
// Base URL points at the versioned API root; override via VITE_API_BASE_URL.
export const apiClient = axios.create({
  baseURL:
    import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1",
  headers: {
    "Content-Type": "application/json",
  },
});
