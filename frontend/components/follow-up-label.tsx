import { AlarmClock, CalendarClock } from "lucide-react";

import { cn } from "@/lib/utils";
import { formatAppDay, formatAppTime } from "@/lib/time";
import type { LeadSummary } from "@/lib/types";

type FollowUpLead = Pick<
  LeadSummary,
  "next_follow_up_at" | "follow_up_due_today" | "follow_up_overdue"
>;

/**
 * Follow-up chip (spec sections 5 and 6). Whether it is due today or overdue
 * comes from the API's flags; this only words it. Overdue is red *and* says
 * "Overdue", so it never relies on colour alone.
 */
export function FollowUpLabel({ lead, now, tz }: { lead: FollowUpLead; now: Date; tz: string }) {
  const at = lead.next_follow_up_at;
  if (!at) return null;

  const time = formatAppTime(at, tz);
  const day = formatAppDay(at, now, tz);
  const dayPhrase = ["Today", "Tomorrow", "Yesterday"].includes(day) ? day.toLowerCase() : day;

  let text: string;
  let tone: string;
  if (lead.follow_up_overdue) {
    text = `Overdue · was due ${dayPhrase} at ${time}`;
    tone = "bg-red-50 text-red-700 ring-red-600/25";
  } else if (lead.follow_up_due_today) {
    text = `Follow-up today at ${time}`;
    tone = "bg-blue-100 text-blue-800 ring-blue-600/25";
  } else {
    text = `${day}, ${time}`;
    tone = "bg-gray-100 text-gray-700 ring-gray-500/20";
  }

  const Icon = lead.follow_up_overdue ? AlarmClock : CalendarClock;
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        tone,
      )}
    >
      <Icon className="size-3.5 shrink-0" aria-hidden="true" />
      <span className="truncate">{text}</span>
    </span>
  );
}
