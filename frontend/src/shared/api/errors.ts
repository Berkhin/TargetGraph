import { isAxiosError } from "axios";

// One item of a FastAPI 422 validation error body.
type FastApiValidationItem = { loc: (string | number)[]; msg: string };

// Extracts a human-readable message from an API failure.
// FastAPI returns `{ detail: ... }` — a string for our explicit HTTPExceptions
// (404 / 422), or an array of items for Pydantic request validation (422).
export function getApiErrorMessage(
  error: unknown,
  fallback = "Что-то пошло не так",
): string {
  if (isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)
      ?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return (
        (detail as FastApiValidationItem[]).map((d) => d.msg).join("; ") ||
        fallback
      );
    }
    // Network / timeout / no response body.
    return error.message;
  }
  return fallback;
}
