// Strict API contract for the Email Discovery & Verification Engine.
// Mirrors backend/app/services/email_verification/models.py.
// Project convention: `type` only — no `interface`, no `any`.

export type VerificationStatus =
  | "VERIFIED" // a deliverable address was confirmed (250)
  | "NOT_FOUND" // MX exists, not catch-all, no candidate accepted
  | "CATCH_ALL" // domain accepts any local-part; needs manual handling
  | "NO_MX_RECORDS" // domain publishes no MX records
  | "INCONCLUSIVE" // graceful degradation (greylisting / transient 4xx)
  | "PROXY_ERROR" // SOCKS5 proxy unreachable
  | "DNS_ERROR"; // MX resolution failed (timeout / SERVFAIL)

// POST /api/v1/contacts/verify-email
export type EmailVerificationRequest = {
  first_name: string;
  last_name: string;
  domain: string;
};

export type SmtpProbeResult = {
  email: string;
  deliverable: boolean;
  smtp_code: number | null;
  smtp_message: string | null;
  error: string | null;
};

export type EmailVerificationResult = {
  domain: string;
  status: VerificationStatus;
  verified_email: string | null;
  mx_host: string | null;
  candidates_generated: number;
  candidates_probed: number;
  probes: ReadonlyArray<SmtpProbeResult>;
  elapsed_ms: number;
  detail: string;
};
