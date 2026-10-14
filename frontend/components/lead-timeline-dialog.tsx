"use client";

import { AlarmClock, AlertTriangle, CalendarClock, Phone, RotateCw, XIcon } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";

import { DiscussionForm } from "@/components/discussion-form";
import { overdueText } from "@/components/follow-up-label";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  ApiError,
  createDiscussion,
  describeApiError,
  getLead,
  isAbortError,
  updateLead,
} from "@/lib/api";
import { STATUS_LABELS, STATUS_OPTIONS } from "@/lib/statuses";
import {
  formatAppDate,
  formatAppDateTime,
  formatAppDay,
  formatAppTime,
  relativeTime,
} from "@/lib/time";
import type {
  DiscussionCreate,
  IsoDateTime,
  LeadDetail,
  LeadStatus,
  LeadSummary,
  LeadUpdate,
} from "@/lib/types";
import { cn } from "@/lib/utils";

interface LeadTimelineDialogProps {
  /** The lead to show. Keep it set until the close animation ends. */
  leadId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenChangeComplete?: (open: boolean) => void;
  /** Called after every successful change, so the dashboard refetches its list. */
  onChanged: () => void;
  now: Date;
  tz: string;
}

/** The lead card's button, found again by id: a change may have re-rendered it elsewhere. */
function findCardButton(leadId: number | null): HTMLElement | null {
  if (leadId === null) return null;
  return document.querySelector<HTMLElement>(`[data-lead-id="${leadId}"]`);
}

/**
 * Timeline dialog (spec sections 5, 6 and 10): lead details, status, next
 * follow-up with Clear, the discussion history newest first, and the form to
 * log a discussion. Every change waits for the server; nothing is optimistic.
 */
export function LeadTimelineDialog({
  leadId,
  open,
  onOpenChange,
  onOpenChangeComplete,
  onChanged,
  now,
  tz,
}: LeadTimelineDialogProps) {
  // Requests still in flight. A note save can overlap a status change or Clear,
  // so they are counted: one finishing must not mark the dialog idle.
  const [pending, setPending] = useState(0);
  const busy = pending > 0;
  const noteRef = useRef<HTMLTextAreaElement>(null);

  function handleOpenChange(next: boolean) {
    if (!next && busy) return; // Esc, backdrop and ✕ all wait for a pending save
    onOpenChange(next);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={handleOpenChange}
      onOpenChangeComplete={onOpenChangeComplete}
    >
      <DialogContent
        showCloseButton={false}
        initialFocus={noteRef}
        finalFocus={() => findCardButton(leadId) ?? true}
        // Full screen below `sm`; about 670 px wide and height-capped above it.
        className="top-0 left-0 flex h-dvh max-h-dvh w-full max-w-none translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none p-0 sm:top-1/2 sm:left-1/2 sm:h-auto sm:max-h-[min(88dvh,820px)] sm:max-w-[670px] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl"
      >
        {leadId !== null ? (
          // A fresh mount per lead and per opening: the detail is always refetched.
          <TimelineContent
            key={leadId}
            leadId={leadId}
            now={now}
            tz={tz}
            busy={busy}
            onRequestStart={() => setPending((count) => count + 1)}
            onRequestEnd={() => setPending((count) => count - 1)}
            onChanged={onChanged}
            noteRef={noteRef}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

interface TimelineContentProps {
  leadId: number;
  now: Date;
  tz: string;
  busy: boolean;
  /** Called once before and once after every save, in pairs. */
  onRequestStart: () => void;
  onRequestEnd: () => void;
  onChanged: () => void;
  noteRef: RefObject<HTMLTextAreaElement | null>;
}

type Saving = "status" | "clear" | null;

function TimelineContent({
  leadId,
  now,
  tz,
  busy,
  onRequestStart,
  onRequestEnd,
  onChanged,
  noteRef,
}: TimelineContentProps) {
  const [detail, setDetail] = useState<LeadDetail | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0); // bumped to refetch
  const [saving, setSaving] = useState<Saving>(null);
  const [pendingStatus, setPendingStatus] = useState<LeadStatus | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // `id` changes on every announcement, so identical texts are still announced.
  const [announcement, setAnnouncement] = useState({ id: 0, text: "" });
  const statusRef = useRef<HTMLSelectElement>(null);
  const followUpRef = useRef<HTMLDivElement>(null);
  // Disabling a focused control (or removing Clear) drops focus to <body>; this
  // is where it goes back once the save settles and the control is enabled again.
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (saving !== null || restoreFocusRef.current === null) return;
    const active = document.activeElement;
    if (active === null || active === document.body) restoreFocusRef.current.focus();
    restoreFocusRef.current = null;
  }, [saving]);

  // Load the detail. Closing the dialog or switching lead unmounts this and
  // aborts the request; a response for any other lead is ignored.
  useEffect(() => {
    const controller = new AbortController();
    getLead(leadId, controller.signal).then(
      (lead) => {
        if (controller.signal.aborted || lead.id !== leadId) return;
        setDetail(lead);
        setLoadError(null);
      },
      (caught: unknown) => {
        if (isAbortError(caught) || controller.signal.aborted) return;
        setLoadError(caught);
      },
    );
    return () => controller.abort();
  }, [leadId, attempt]);

  function reload() {
    setLoadError(null);
    setAttempt((current) => current + 1);
  }

  function announce(text: string) {
    setAnnouncement((previous) => ({ id: previous.id + 1, text }));
  }

  /** The header always comes from the server's response, never a local guess. */
  function applySummary(lead: LeadSummary) {
    setDetail((current) => (current && current.id === lead.id ? { ...current, ...lead } : current));
  }

  async function patch(kind: Exclude<Saving, null>, changes: LeadUpdate, success: string) {
    restoreFocusRef.current = kind === "status" ? statusRef.current : followUpRef.current;
    setSaving(kind);
    setActionError(null);
    onRequestStart();
    try {
      applySummary(await updateLead(leadId, changes));
      announce(success);
      onChanged();
    } catch (error) {
      const action = kind === "status" ? "Couldn't change the status." : "Couldn't clear the follow-up.";
      setActionError(`${action} ${describeApiError(error)}`);
    } finally {
      setPendingStatus(null); // on failure the select falls back to the saved status
      setSaving(null);
      onRequestEnd();
    }
  }

  function changeStatus(status: LeadStatus) {
    if (detail === null || saving !== null || status === detail.status) return;
    setPendingStatus(status);
    void patch("status", { status }, `Status changed to ${STATUS_LABELS[status]}`);
  }

  function clearFollowUp() {
    if (saving !== null) return;
    void patch("clear", { next_follow_up_at: null }, "Follow-up cleared");
  }

  async function saveNote(data: DiscussionCreate) {
    onRequestStart();
    try {
      const { discussion, lead } = await createDiscussion(leadId, data);
      if (detail === null) {
        reload(); // the history never loaded, so fetch it whole
      } else {
        setDetail((current) =>
          current && current.id === lead.id
            ? { ...current, ...lead, discussions: [discussion, ...current.discussions] }
            : current,
        );
      }
      announce("Note saved");
      onChanged();
    } finally {
      onRequestEnd();
    }
  }

  return (
    <>
      <p role="status" aria-live="polite" className="sr-only">
        <span key={announcement.id}>{announcement.text}</span>
      </p>

      <header className="shrink-0 border-b px-5 pt-4 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 pt-0.5">
            {detail ? (
              <DialogTitle className="text-lg leading-snug font-semibold">
                {detail.name}
                {detail.company ? (
                  <span className="font-normal text-muted-foreground"> ({detail.company})</span>
                ) : null}
              </DialogTitle>
            ) : (
              <>
                <DialogTitle className="sr-only">Lead timeline</DialogTitle>
                {loadError === null ? (
                  <div aria-hidden="true" className="flex flex-col gap-2 py-1">
                    <div className="h-5 w-48 animate-pulse rounded bg-gray-200" />
                    <div className="h-3.5 w-32 animate-pulse rounded bg-gray-100" />
                  </div>
                ) : null}
              </>
            )}
            <DialogDescription className="sr-only">
              Lead details, discussion history newest first, and a form to log a new discussion.
            </DialogDescription>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            {detail ? (
              <>
                <label htmlFor="lead-status" className="sr-only">
                  Status
                </label>
                <select
                  ref={statusRef}
                  id="lead-status"
                  value={pendingStatus ?? detail.status}
                  onChange={(event) => changeStatus(event.target.value as LeadStatus)}
                  disabled={saving !== null}
                  aria-busy={saving === "status"}
                  className="h-8 rounded-lg border border-input bg-white px-2 text-sm font-medium outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60"
                >
                  {STATUS_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </>
            ) : null}
            <DialogClose render={<Button variant="ghost" size="icon-sm" disabled={busy} />}>
              <XIcon />
              <span className="sr-only">Close</span>
            </DialogClose>
          </div>
        </div>

        {detail ? (
          <div className="mt-1 flex flex-col gap-1 text-sm">
            {detail.phone ? (
              <p className="flex items-center gap-1.5 text-muted-foreground">
                <Phone className="size-3.5 shrink-0" aria-hidden="true" />
                <span className="sr-only">Phone:</span>
                {detail.phone}
              </p>
            ) : null}
            {/* Focusable by script only: it receives focus after Clear. */}
            <div ref={followUpRef} tabIndex={-1} className="rounded-sm outline-none">
              <NextFollowUp
                lead={detail}
                now={now}
                tz={tz}
                clearing={saving === "clear"}
                disabled={saving !== null}
                onClear={clearFollowUp}
              />
            </div>
          </div>
        ) : null}

        {actionError ? (
          <p role="alert" className="mt-2 text-sm text-red-700">
            {actionError}
          </p>
        ) : null}
      </header>

      <div
        role="region"
        aria-label="Discussion history"
        tabIndex={0}
        className="min-h-0 flex-1 overflow-y-auto bg-gray-50 px-5 py-4 outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset"
      >
        {detail ? (
          <Timeline lead={detail} now={now} tz={tz} />
        ) : loadError !== null ? (
          <LoadError error={loadError} onRetry={reload} />
        ) : (
          <TimelineSkeleton />
        )}
      </div>

      <div className="shrink-0 border-t bg-white px-5 py-4">
        <DiscussionForm tz={tz} noteRef={noteRef} onSubmit={saveNote} />
      </div>
    </>
  );
}

interface NextFollowUpProps {
  lead: LeadSummary;
  now: Date;
  tz: string;
  clearing: boolean;
  disabled: boolean;
  onClear: () => void;
}

/** "Next follow-up: Today, 2:00 PM · Clear" (spec section 5, deviation 4). */
function NextFollowUp({ lead, now, tz, clearing, disabled, onClear }: NextFollowUpProps) {
  const at = lead.next_follow_up_at;
  if (!at) return <p className="text-muted-foreground">Next follow-up: None</p>;

  return (
    <div className="flex flex-wrap items-center gap-x-1.5">
      <span className="text-muted-foreground">Next follow-up:</span>
      {lead.follow_up_overdue ? (
        // Red and worded, so overdue never relies on colour alone.
        <span className="inline-flex items-center gap-1 font-medium text-red-700">
          <AlarmClock className="size-3.5 shrink-0" aria-hidden="true" />
          {overdueText(at, now, tz)}
        </span>
      ) : (
        <span className={cn("font-medium", lead.follow_up_due_today && "text-blue-700")}>
          {formatAppDay(at, now, tz)}, {formatAppTime(at, tz)}
        </span>
      )}
      <span aria-hidden="true" className="text-muted-foreground">
        ·
      </span>
      <button
        type="button"
        onClick={onClear}
        disabled={disabled}
        aria-busy={clearing}
        className="rounded-sm font-medium text-blue-700 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none disabled:opacity-50"
      >
        {clearing ? "Clearing…" : "Clear"}
        <span className="sr-only"> follow-up</span>
      </button>
    </div>
  );
}

/** History newest first, then the synthetic "Lead created" entry (never a discussion). */
function Timeline({ lead, now, tz }: { lead: LeadDetail; now: Date; tz: string }) {
  return (
    <ol className="flex flex-col gap-5">
      {lead.discussions.map((discussion, index) => (
        <TimelineEntry key={discussion.id} at={discussion.created_at} newest={index === 0} now={now} tz={tz}>
          <div className="rounded-lg border bg-white p-3 text-sm shadow-xs">
            <p className="break-words whitespace-pre-wrap">{discussion.note}</p>
            {discussion.follow_up_at ? (
              <p className="mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-800 ring-1 ring-blue-600/20 ring-inset">
                <CalendarClock className="size-3.5 shrink-0" aria-hidden="true" />
                Follow-up set for: {formatAppDateTime(discussion.follow_up_at, now, tz)}
              </p>
            ) : null}
          </div>
        </TimelineEntry>
      ))}
      <TimelineEntry at={lead.created_at} newest={lead.discussions.length === 0} last now={now} tz={tz}>
        <p className="text-sm text-muted-foreground italic">Lead created</p>
      </TimelineEntry>
    </ol>
  );
}

interface TimelineEntryProps {
  at: IsoDateTime;
  newest: boolean;
  last?: boolean;
  now: Date;
  tz: string;
  children: ReactNode;
}

/** "May 4, 10:30 AM (2 days ago)" above the content, with a dot on the vertical line. */
function TimelineEntry({ at, newest, last = false, now, tz, children }: TimelineEntryProps) {
  const relative = relativeTime(at, now, tz);
  // After a week relativeTime is itself a date, which would only repeat it.
  const showRelative = relative !== formatAppDate(at, now, tz);
  return (
    <li
      className={cn(
        "relative pl-7",
        // The line runs from this dot down to the next one (across the gap).
        !last && "before:absolute before:top-4 before:-bottom-5 before:left-[7px] before:w-0.5 before:bg-gray-200",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "absolute top-0 left-0 size-4 rounded-full border-2 border-gray-50",
          newest ? "bg-blue-600" : "bg-gray-300",
        )}
      />
      <time dateTime={at} className="block text-xs leading-4 text-muted-foreground">
        {formatAppDateTime(at, now, tz)}
        {showRelative ? ` (${relative})` : null}
      </time>
      <div className="mt-1.5">{children}</div>
    </li>
  );
}

function TimelineSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <p role="status" className="sr-only">
        Loading discussions…
      </p>
      {[0, 1].map((key) => (
        <div key={key} aria-hidden="true" className="flex flex-col gap-2 pl-7">
          <div className="h-3 w-40 animate-pulse rounded bg-gray-200" />
          <div className="h-14 animate-pulse rounded-lg bg-gray-100" />
        </div>
      ))}
    </div>
  );
}

function LoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const gone = error instanceof ApiError && error.code === "lead_not_found";
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
    >
      <span className="flex items-center gap-2">
        <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
        {gone ? describeApiError(error) : `Couldn't load this lead. ${describeApiError(error)}`}
      </span>
      {gone ? null : (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCw aria-hidden="true" />
          Retry
        </Button>
      )}
    </div>
  );
}
