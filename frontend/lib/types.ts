// TypeScript mirror of the backend's API contract (backend/app/schemas.py and
// /openapi.json). Keep these in sync with the backend; do not invent fields.

/**
 * An ISO 8601 instant. Responses are always UTC with a "Z" suffix; requests
 * must include an offset (naive date-times are rejected with 422).
 */
export type IsoDateTime = string;

export const LEAD_STATUSES = [
  "new",
  "contacted",
  "qualified",
  "proposal_sent",
  "won",
  "lost",
] as const;

export type LeadStatus = (typeof LEAD_STATUSES)[number];

// --- Responses ----------------------------------------------------------------

export interface HealthResponse {
  status: "ok";
  database: "ok";
}

export interface LastDiscussion {
  note: string;
  created_at: IsoDateTime;
}

export interface LeadSummary {
  id: number;
  name: string;
  company: string | null;
  phone: string | null;
  status: LeadStatus;
  next_follow_up_at: IsoDateTime | null;
  follow_up_due_today: boolean;
  follow_up_overdue: boolean;
  last_discussion: LastDiscussion | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface Discussion {
  id: number;
  note: string;
  follow_up_at: IsoDateTime | null;
  created_at: IsoDateTime;
}

/** GET /api/leads/{id}: the summary plus full history, newest first. */
export interface LeadDetail extends LeadSummary {
  discussions: Discussion[];
}

/** POST /api/leads/{id}/discussions. */
export interface DiscussionCreated {
  discussion: Discussion;
  lead: LeadSummary;
}

export interface ApiErrorItem {
  /** Request field the message belongs to; null when it concerns the whole request. */
  field: string | null;
  message: string;
}

/** The backend's envelope for every non-2xx response. */
export interface ErrorResponse {
  detail: string;
  code: string;
  errors: ApiErrorItem[];
}

// --- Requests -----------------------------------------------------------------

/** POST /api/leads. Status is not accepted: new leads always start as "new". */
export interface LeadCreate {
  name: string;
  company?: string | null;
  phone?: string | null;
}

/**
 * PATCH /api/leads/{id}. Omit a property to leave it unchanged; send
 * `next_follow_up_at: null` to clear the follow-up. Status cannot be null.
 * At least one property is required (an empty body is a 422).
 */
export interface LeadUpdate {
  status?: LeadStatus;
  next_follow_up_at?: IsoDateTime | null;
}

/**
 * POST /api/leads/{id}/discussions. An omitted or null follow_up_at leaves the
 * lead's current follow-up unchanged; a value replaces it.
 */
export interface DiscussionCreate {
  note: string;
  follow_up_at?: IsoDateTime | null;
}

/** GET /api/leads query. Omit `status` for "All"; a blank `q` means no search. */
export interface LeadListFilters {
  status?: LeadStatus;
  q?: string;
}
