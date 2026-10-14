import { LEAD_STATUSES, type LeadStatus } from "@/lib/types";

/** Display labels for the backend's canonical status values. */
export const STATUS_LABELS: Readonly<Record<LeadStatus, string>> = {
  new: "New",
  contacted: "Contacted",
  qualified: "Qualified",
  proposal_sent: "Proposal Sent",
  won: "Won",
  lost: "Lost",
};

/**
 * Badge colours from the specification (section 5). The label is always shown
 * as text, so status is never conveyed by colour alone.
 */
export const STATUS_BADGE_CLASSES: Readonly<Record<LeadStatus, string>> = {
  new: "bg-green-100 text-green-800 ring-green-600/20",
  contacted: "bg-amber-100 text-amber-900 ring-amber-600/25",
  qualified: "bg-blue-100 text-blue-800 ring-blue-600/20",
  proposal_sent: "bg-purple-100 text-purple-800 ring-purple-600/20",
  won: "bg-gray-200 text-gray-800 ring-gray-500/20",
  lost: "bg-red-100 text-red-800 ring-red-600/20",
};

/** Closed statuses: their cards use muted text (spec section 5). */
export const CLOSED_STATUSES: ReadonlySet<LeadStatus> = new Set<LeadStatus>(["won", "lost"]);

/** All statuses in pipeline order, e.g. for filter pills and the status select. */
export const STATUS_OPTIONS = LEAD_STATUSES.map((value) => ({
  value,
  label: STATUS_LABELS[value],
}));
