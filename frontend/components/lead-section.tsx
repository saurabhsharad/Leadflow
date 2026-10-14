import type { ReactNode } from "react";

import { LeadCard } from "@/components/lead-card";
import type { LeadSummary } from "@/lib/types";

interface LeadSectionProps {
  id: string;
  title: string;
  icon?: ReactNode;
  leads: LeadSummary[];
  now: Date;
  tz: string;
  emptyMessage: string;
  pinned?: boolean;
  onOpenLead: (leadId: number) => void;
}

/** One dashboard group: heading, cards in the API's order, or an empty message. */
export function LeadSection({
  id,
  title,
  icon,
  leads,
  now,
  tz,
  emptyMessage,
  pinned,
  onOpenLead,
}: LeadSectionProps) {
  const headingId = `${id}-heading`;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2
        id={headingId}
        className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-widest text-muted-foreground"
      >
        {icon}
        {title}
        <span className="sr-only">({leads.length})</span>
      </h2>
      {leads.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {leads.map((lead) => (
            <li key={lead.id}>
              <LeadCard lead={lead} now={now} tz={tz} pinned={pinned} onOpen={onOpenLead} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-lg border border-dashed bg-white px-4 py-6 text-center text-sm text-muted-foreground">
          {emptyMessage}
        </p>
      )}
    </section>
  );
}
