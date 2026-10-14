import type { LeadSummary } from "@/lib/types";

export interface DashboardGroups {
  /** Follow-up before today (overdue and not due today): oldest first. */
  overdueEarlier: LeadSummary[];
  /** Follow-up today, including ones already overdue: earliest first. */
  today: LeadSummary[];
  /** Everything else: latest discussion first, leads without discussions last. */
  allLeads: LeadSummary[];
}

/**
 * Split the API's list into the three dashboard groups (spec section 6).
 *
 * GET /api/leads already returns the leads sorted in exactly this group order,
 * so this only partitions it by the API's two flags, keeping that order and
 * placing every lead in exactly one group. No dates are compared here.
 */
export function groupLeads(leads: readonly LeadSummary[]): DashboardGroups {
  const groups: DashboardGroups = { overdueEarlier: [], today: [], allLeads: [] };
  for (const lead of leads) {
    if (lead.follow_up_due_today) groups.today.push(lead);
    else if (lead.follow_up_overdue) groups.overdueEarlier.push(lead);
    else groups.allLeads.push(lead);
  }
  return groups;
}
