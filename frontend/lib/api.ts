// Typed client for the LeadFlow API. The browser calls FastAPI directly; every
// HTTP and error-handling detail lives here, not in components.

import { getApiBaseUrl } from "@/lib/config";
import type {
  ApiErrorItem,
  DiscussionCreate,
  DiscussionCreated,
  ErrorResponse,
  HealthResponse,
  LeadCreate,
  LeadDetail,
  LeadListFilters,
  LeadSummary,
  LeadUpdate,
} from "@/lib/types";

/**
 * Any failed request. `code` is the backend's error code (e.g. "validation_error",
 * "lead_not_found", "database_unavailable"), or "network_error" when the server
 * could not be reached, or "http_error" when the response was not the envelope.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly errors: ApiErrorItem[];
  /** First message per request field, for showing under the matching input. */
  readonly fieldErrors: Readonly<Record<string, string>>;

  constructor(status: number, code: string, message: string, errors: ApiErrorItem[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.errors = errors;
    const fieldErrors: Record<string, string> = {};
    for (const { field, message: text } of errors) {
      if (field && !(field in fieldErrors)) fieldErrors[field] = text;
    }
    this.fieldErrors = fieldErrors;
  }
}

/** True for requests cancelled through an AbortSignal; callers usually ignore these. */
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/** A short, user-facing sentence for a failed request (spec section 10). */
export function describeApiError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "network_error") return "Server unavailable. Check your connection and try again.";
    if (error.code === "database_unavailable") return "The server can't reach its database. Try again shortly.";
    if (error.code === "lead_not_found") return "This lead no longer exists.";
    return error.message;
  }
  return "Something went wrong. Please try again.";
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH";
  query?: URLSearchParams;
  body?: unknown;
  signal?: AbortSignal;
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  if (typeof value !== "object" || value === null) return false;
  const body = value as Record<string, unknown>;
  return typeof body.detail === "string" && typeof body.code === "string";
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", query, body, signal } = options;
  const queryString = query?.toString();
  const url = `${getApiBaseUrl()}${path}${queryString ? `?${queryString}` : ""}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      signal,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      // JSON.stringify drops undefined properties, so "omitted" stays omitted
      // while an explicit null is sent as null (PATCH relies on this).
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError(0, "network_error", "Server unavailable");
  }

  const data = await readJson(response);
  if (!response.ok) {
    if (isErrorResponse(data)) {
      throw new ApiError(response.status, data.code, data.detail, data.errors ?? []);
    }
    throw new ApiError(response.status, "http_error", `Request failed (HTTP ${response.status})`);
  }
  if (data === undefined) {
    throw new ApiError(response.status, "invalid_response", "The server sent an unreadable response");
  }
  return data as T;
}

// --- Endpoints ----------------------------------------------------------------------

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health", { signal });
}

/** Leads in dashboard order (overdue from earlier days, today, then the rest). */
export function listLeads(filters: LeadListFilters = {}, signal?: AbortSignal): Promise<LeadSummary[]> {
  const query = new URLSearchParams();
  // "All" means no status parameter at all: the backend rejects status="".
  if (filters.status) query.set("status", filters.status);
  const search = filters.q?.trim();
  if (search) query.set("q", search);
  return request<LeadSummary[]>("/api/leads", { query, signal });
}

export function createLead(data: LeadCreate, signal?: AbortSignal): Promise<LeadSummary> {
  return request<LeadSummary>("/api/leads", { method: "POST", body: data, signal });
}

export function getLead(leadId: number, signal?: AbortSignal): Promise<LeadDetail> {
  return request<LeadDetail>(`/api/leads/${encodeURIComponent(leadId)}`, { signal });
}

/** Partial update: omitted properties are untouched; `next_follow_up_at: null` clears it. */
export function updateLead(
  leadId: number,
  changes: LeadUpdate,
  signal?: AbortSignal,
): Promise<LeadSummary> {
  return request<LeadSummary>(`/api/leads/${encodeURIComponent(leadId)}`, {
    method: "PATCH",
    body: changes,
    signal,
  });
}

export function createDiscussion(
  leadId: number,
  data: DiscussionCreate,
  signal?: AbortSignal,
): Promise<DiscussionCreated> {
  return request<DiscussionCreated>(`/api/leads/${encodeURIComponent(leadId)}/discussions`, {
    method: "POST",
    body: data,
    signal,
  });
}
