"use client";

import { AlertTriangle, Pin, Plus, RotateCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { AddLeadDialog } from "@/components/add-lead-dialog";
import { LeadCardSkeleton } from "@/components/lead-card";
import { LeadFilters } from "@/components/lead-filters";
import { LeadSection } from "@/components/lead-section";
import { LeadTimelineDialog } from "@/components/lead-timeline-dialog";
import { SiteHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { ApiError, isAbortError, listLeads } from "@/lib/api";
import { getAppTimezone } from "@/lib/config";
import { groupLeads } from "@/lib/dashboard";
import type { LeadStatus, LeadSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const SEARCH_DEBOUNCE_MS = 300;
const REFRESH_INTERVAL_MS = 60_000;

interface Filters {
  status: LeadStatus | undefined;
  query: string;
}

interface LoadedList extends Filters {
  leads: LeadSummary[];
}

function sameFilters(a: Filters, b: Filters): boolean {
  return a.status === b.status && a.query === b.query;
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "network_error") return "Can't reach the server.";
    if (error.code === "database_unavailable") return "The server can't reach its database.";
    return `Couldn't load leads: ${error.message}.`;
  }
  return error instanceof Error ? error.message : "Couldn't load leads.";
}

function readTimezone(): { tz: string; configError: string | null } {
  try {
    return { tz: getAppTimezone(), configError: null };
  } catch (error) {
    return { tz: "UTC", configError: (error as Error).message };
  }
}

/** The dashboard: filters plus the three follow-up groups (spec sections 5, 6, 10). */
export function LeadDashboard() {
  const [{ tz, configError }] = useState(readTimezone);
  const [status, setStatus] = useState<LeadStatus | undefined>(undefined);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState(""); // `search`, trimmed and debounced
  const [list, setList] = useState<LoadedList | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [now, setNow] = useState<Date | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  // The id outlives `timelineOpen` until the close animation ends.
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const [timelineOpen, setTimelineOpen] = useState(false);
  // `id` changes on every announcement, so identical texts are still announced.
  const [announcement, setAnnouncement] = useState({ id: 0, text: "" });

  /** The single entry point for (re)loading: aborts any list request still in flight. */
  const refreshLeads = useCallback(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const isCurrent = () => controllerRef.current === controller; // not superseded meanwhile
    // State changes only in the promise callbacks, never synchronously.
    listLeads({ status, q: query }, controller.signal).then(
      (leads) => {
        if (!isCurrent()) return;
        setList({ leads, status, query });
        setError(null);
        setNow(new Date());
      },
      (caught: unknown) => {
        if (isAbortError(caught) || !isCurrent()) return;
        setError(caught); // the last good list stays on screen
        setNow(new Date());
      },
    );
  }, [status, query]);

  // Debounce typing; the request goes out once the user pauses.
  useEffect(() => {
    const handle = setTimeout(() => setQuery(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [search]);

  // Load on mount and whenever the filters change.
  useEffect(() => {
    refreshLeads();
  }, [refreshLeads]);

  // Freshness: every 60 s while the tab is visible, and on window focus.
  useEffect(() => {
    const interval = setInterval(() => {
      if (document.visibilityState === "visible") refreshLeads();
    }, REFRESH_INTERVAL_MS);
    const onFocus = () => refreshLeads();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", onFocus);
    };
  }, [refreshLeads]);

  // Cancel any request still in flight when the dashboard unmounts.
  useEffect(() => () => controllerRef.current?.abort(), []);

  const current: Filters = { status, query };
  const updating = list !== null && !sameFilters(list, current);

  function handleCreated(lead: LeadSummary) {
    // Keep the active filters; the new lead shows up if it matches them.
    setAnnouncement((previous) => ({ id: previous.id + 1, text: `Lead added: ${lead.name}` }));
    refreshLeads();
  }

  function openTimeline(leadId: number) {
    setSelectedLeadId(leadId);
    setTimelineOpen(true);
  }

  return (
    <>
      <SiteHeader
        actions={
          <Button
            onClick={() => setAddOpen(true)}
            className="bg-blue-600 text-white hover:bg-blue-700"
          >
            <Plus aria-hidden="true" />
            Add New Lead
          </Button>
        }
      />
      {/* Content column: about 1,000 px on desktop, full width with padding on mobile. */}
      <main id="content" className="mx-auto w-full max-w-5xl flex-1 px-4 py-6 sm:px-6 sm:py-8">
        <div className="flex flex-col gap-6">
          <h1 className="sr-only">Lead dashboard</h1>
          <p role="status" aria-live="polite" className="sr-only">
            {/* A new key replaces the text node, which screen readers announce again. */}
            <span key={announcement.id}>{announcement.text}</span>
          </p>

          {configError ? <ErrorBanner message={configError} /> : null}

          <LeadFilters
            status={status}
            onStatusChange={setStatus}
            search={search}
            onSearchChange={setSearch}
          />

          {error !== null ? (
            <ErrorBanner message={describeError(error)} onRetry={refreshLeads} />
          ) : null}

          {list === null || now === null ? (
            error === null ? <LoadingSections /> : null
          ) : (
            <LeadGroups
              list={list}
              now={now}
              tz={tz}
              updating={updating}
              onOpenLead={openTimeline}
            />
          )}
        </div>
      </main>
      <AddLeadDialog open={addOpen} onOpenChange={setAddOpen} onCreated={handleCreated} />
      {now !== null ? (
        <LeadTimelineDialog
          leadId={selectedLeadId}
          open={timelineOpen}
          onOpenChange={setTimelineOpen}
          onOpenChangeComplete={(isOpen) => {
            if (!isOpen) setSelectedLeadId(null);
          }}
          onChanged={refreshLeads}
          now={now}
          tz={tz}
        />
      ) : null}
    </>
  );
}

function LeadGroups({
  list,
  now,
  tz,
  updating,
  onOpenLead,
}: {
  list: LoadedList;
  now: Date;
  tz: string;
  updating: boolean;
  onOpenLead: (leadId: number) => void;
}) {
  const groups = groupLeads(list.leads);
  const filtered = list.status !== undefined || list.query !== "";
  let allLeadsEmpty = "No leads yet.";
  if (list.leads.length > 0) allLeadsEmpty = "No other leads.";
  else if (filtered) allLeadsEmpty = "No leads match these filters.";

  return (
    <div
      aria-busy={updating}
      className={cn("flex flex-col gap-8 transition-opacity", updating && "opacity-60")}
    >
      <p role="status" className="sr-only">
        {list.leads.length === 1 ? "1 lead" : `${list.leads.length} leads`}
      </p>

      {groups.overdueEarlier.length > 0 ? (
        <LeadSection
          id="overdue"
          title="Overdue from earlier days"
          icon={<AlertTriangle className="size-3.5 text-red-600" aria-hidden="true" />}
          leads={groups.overdueEarlier}
          now={now}
          tz={tz}
          emptyMessage=""
          onOpenLead={onOpenLead}
        />
      ) : null}

      <LeadSection
        id="today"
        title="Today's follow-ups"
        icon={<Pin className="size-3.5" aria-hidden="true" />}
        leads={groups.today}
        now={now}
        tz={tz}
        pinned
        emptyMessage={filtered ? "No follow-ups today match these filters" : "No follow-ups today"}
        onOpenLead={onOpenLead}
      />

      <LeadSection
        id="all-leads"
        title="All leads"
        leads={groups.allLeads}
        now={now}
        tz={tz}
        emptyMessage={allLeadsEmpty}
        onOpenLead={onOpenLead}
      />
    </div>
  );
}

function LoadingSections() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true">
      <p role="status" className="sr-only">
        Loading leads…
      </p>
      <LeadCardSkeleton />
      <LeadCardSkeleton />
      <LeadCardSkeleton />
    </div>
  );
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
    >
      <span className="flex items-center gap-2">
        <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
        {message}
      </span>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCw aria-hidden="true" />
          Retry
        </Button>
      ) : null}
    </div>
  );
}
