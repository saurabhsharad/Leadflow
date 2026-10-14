import { FollowUpLabel } from "@/components/follow-up-label";
import { StatusBadge } from "@/components/status-badge";
import { CLOSED_STATUSES } from "@/lib/statuses";
import { relativeTime } from "@/lib/time";
import type { LeadSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

interface LeadCardProps {
  lead: LeadSummary;
  now: Date;
  tz: string;
  /** Today's follow-ups use the light-blue pinned style (spec section 5). */
  pinned?: boolean;
}

export function LeadCard({ lead, now, tz, pinned = false }: LeadCardProps) {
  const muted = CLOSED_STATUSES.has(lead.status);
  const last = lead.last_discussion;

  return (
    <article
      aria-labelledby={`lead-${lead.id}-name`}
      className={cn(
        "flex flex-col gap-2 rounded-lg border bg-white p-4 shadow-xs",
        pinned && "border-blue-300 bg-blue-50",
        muted && "text-muted-foreground",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 id={`lead-${lead.id}-name`} className="min-w-0 text-base leading-snug">
          <span className={cn("font-semibold", !muted && "text-foreground")}>{lead.name}</span>
          {lead.company ? (
            <span className="font-normal text-muted-foreground"> ({lead.company})</span>
          ) : null}
        </h3>
        <StatusBadge status={lead.status} />
      </div>

      {lead.next_follow_up_at ? (
        <div>
          <FollowUpLabel lead={lead} now={now} tz={tz} />
        </div>
      ) : null}

      {last ? (
        <div className="flex flex-col gap-0.5 text-sm sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
          <p className="min-w-0 truncate">
            <span className="font-semibold">Last Note:</span> {last.note}
          </p>
          <time
            dateTime={last.created_at}
            className="shrink-0 text-xs text-muted-foreground"
          >
            {relativeTime(last.created_at, now, tz)}
          </time>
        </div>
      ) : (
        <p className="text-sm italic text-muted-foreground">No discussions yet</p>
      )}
    </article>
  );
}

/** Placeholder card while the list loads (no time-dependent text). */
export function LeadCardSkeleton() {
  return (
    <div aria-hidden="true" className="flex flex-col gap-3 rounded-lg border bg-white p-4">
      <div className="flex justify-between gap-3">
        <div className="h-4 w-40 animate-pulse rounded bg-gray-200" />
        <div className="h-4 w-16 animate-pulse rounded-full bg-gray-200" />
      </div>
      <div className="h-3 w-3/4 animate-pulse rounded bg-gray-100" />
    </div>
  );
}
