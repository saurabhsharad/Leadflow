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

/** All statuses in pipeline order, e.g. for filter pills and the status select. */
export const STATUS_OPTIONS = LEAD_STATUSES.map((value) => ({
  value,
  label: STATUS_LABELS[value],
}));
