"use client";

import { useEffect, useRef, useState, type FormEvent, type RefObject } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, describeApiError } from "@/lib/api";
import { timezoneLabel, toAppInstant } from "@/lib/time";
import type { DiscussionCreate, IsoDateTime } from "@/lib/types";
import { charCount, cn } from "@/lib/utils";

// Same rules as the backend's DiscussionCreate (backend/app/schemas.py). The
// backend stays authoritative; these checks only give faster feedback.
const NOTE_MAX = 5000;
const FOLLOW_UP_START = Date.UTC(2000, 0, 1); // inclusive, UTC
const FOLLOW_UP_END = Date.UTC(2101, 0, 1); // exclusive, UTC
// How often the "time has passed" hint is re-checked while the form is open.
const PAST_CHECK_MS = 15_000;

type Field = "note" | "follow_up_at";
type FieldErrors = Partial<Record<Field, string>>;
const FIELDS: Field[] = ["note", "follow_up_at"];

function isPast(instant: IsoDateTime | null): boolean {
  return instant !== null && Date.parse(instant) < Date.now();
}

interface DiscussionFormProps {
  tz: string;
  noteRef: RefObject<HTMLTextAreaElement | null>;
  /** Saves the discussion; a rejection keeps the typed values and shows the error. */
  onSubmit: (data: DiscussionCreate) => Promise<void>;
}

/**
 * "Log a new discussion" with an optional follow-up (spec sections 5, 6 and 10).
 * Date and time are wall-clock values in the app timezone, never the browser's.
 * Without a follow-up the request omits it, so the lead's follow-up is untouched.
 */
export function DiscussionForm({ tz, noteRef, onSubmit }: DiscussionFormProps) {
  const [note, setNote] = useState("");
  const [followUp, setFollowUp] = useState(false);
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [past, setPast] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const dateRef = useRef<HTMLInputElement>(null);

  const zone = timezoneLabel(tz);
  const instant = followUp ? toAppInstant(date, time, tz) : null;
  const incomplete = followUp && (date === "" || time === "");

  // Keep the past-time hint honest while the form sits open.
  useEffect(() => {
    if (instant === null) return;
    const handle = setInterval(() => setPast(isPast(instant)), PAST_CHECK_MS);
    return () => clearInterval(handle);
  }, [instant]);

  function clearFieldError(field: Field) {
    if (fieldErrors[field]) setFieldErrors((current) => ({ ...current, [field]: undefined }));
  }

  function changeFollowUp(nextDate: string, nextTime: string) {
    setDate(nextDate);
    setTime(nextTime);
    setPast(isPast(toAppInstant(nextDate, nextTime, tz)));
    clearFieldError("follow_up_at");
  }

  function toggleFollowUp(checked: boolean) {
    setFollowUp(checked);
    if (!checked) changeFollowUp("", ""); // unticking discards the date and time
  }

  function showFieldErrors(errors: FieldErrors) {
    setFieldErrors(errors);
    if (errors.note) noteRef.current?.focus();
    else if (errors.follow_up_at) dateRef.current?.focus();
  }

  function validate(): FieldErrors {
    const errors: FieldErrors = {};
    const trimmed = note.trim();
    if (!trimmed) errors.note = "Note is required";
    else if (charCount(trimmed) > NOTE_MAX) {
      errors.note = `Note must be at most 5,000 characters (it has ${charCount(trimmed).toLocaleString("en-US")})`;
    }
    if (followUp) {
      // Native inputs rarely allow this (e.g. a six-digit year), but check anyway.
      if (instant === null) errors.follow_up_at = "Choose a valid date and time.";
      else {
        const at = Date.parse(instant);
        if (at < FOLLOW_UP_START || at >= FOLLOW_UP_END) {
          errors.follow_up_at = "Year must be between 2000 and 2100 (UTC)";
        }
      }
    }
    return errors;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || incomplete) return;

    const clientErrors = validate();
    if (Object.keys(clientErrors).length > 0) {
      setFormError(null);
      showFieldErrors(clientErrors);
      return;
    }

    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);
    try {
      // Omitting follow_up_at (rather than sending null) keeps the lead's follow-up.
      await onSubmit(instant ? { note: note.trim(), follow_up_at: instant } : { note: note.trim() });
      setNote("");
      setFollowUp(false);
      changeFollowUp("", "");
      noteRef.current?.focus();
    } catch (error) {
      // Everything typed stays in place.
      const serverFieldErrors: FieldErrors = {};
      if (error instanceof ApiError) {
        for (const field of FIELDS) {
          if (error.fieldErrors[field]) serverFieldErrors[field] = error.fieldErrors[field];
        }
      }
      const otherErrors =
        error instanceof ApiError &&
        error.errors.some((item) => !item.field || !FIELDS.includes(item.field as Field));
      if (Object.keys(serverFieldErrors).length > 0) showFieldErrors(serverFieldErrors);
      else noteRef.current?.focus(); // the disabled Save button dropped focus
      if (Object.keys(serverFieldErrors).length === 0 || otherErrors) {
        setFormError(describeApiError(error));
      }
    } finally {
      setSubmitting(false);
    }
  }

  const followUpMessageId = "discussion-follow-up-message";
  let followUpMessage: { text: string; tone: string } | null = null;
  if (fieldErrors.follow_up_at) {
    followUpMessage = { text: fieldErrors.follow_up_at, tone: "text-red-700" };
  } else if (incomplete) {
    followUpMessage = { text: "Choose a date and time.", tone: "text-muted-foreground" };
  } else if (instant !== null && past) {
    followUpMessage = {
      text: "This time has passed — it will show as overdue.",
      tone: "text-amber-800",
    };
  }

  return (
    <form noValidate onSubmit={handleSubmit} className="flex flex-col gap-3">
      {formError ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
        >
          {formError}
        </p>
      ) : null}

      <div className="grid gap-1.5">
        <label htmlFor="discussion-note" className="sr-only">
          New discussion note
        </label>
        <textarea
          ref={noteRef}
          id="discussion-note"
          value={note}
          onChange={(event) => {
            setNote(event.target.value);
            clearFieldError("note");
          }}
          placeholder="Log a new discussion..."
          rows={3}
          readOnly={submitting}
          aria-invalid={fieldErrors.note ? true : undefined}
          aria-describedby={fieldErrors.note ? "discussion-note-error" : undefined}
          className="min-h-20 w-full resize-y rounded-lg border border-input bg-white px-2.5 py-2 text-base transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 md:text-sm"
        />
        {fieldErrors.note ? (
          <p id="discussion-note-error" className="text-sm text-red-700">
            {fieldErrors.note}
          </p>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-center gap-2">
          <input
            id="discussion-set-follow-up"
            type="checkbox"
            checked={followUp}
            onChange={(event) => toggleFollowUp(event.target.checked)}
            disabled={submitting}
            className="size-4 rounded border-input accent-gray-900 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          <label htmlFor="discussion-set-follow-up" className="text-sm font-medium">
            Set Follow-up
          </label>
        </div>

        <div className="flex items-center gap-2">
          <label htmlFor="discussion-follow-up-date" className="sr-only">
            Follow-up date ({zone})
          </label>
          <Input
            ref={dateRef}
            id="discussion-follow-up-date"
            type="date"
            value={date}
            onChange={(event) => changeFollowUp(event.target.value, time)}
            min="2000-01-01"
            max="2100-12-31"
            disabled={!followUp || submitting}
            aria-invalid={fieldErrors.follow_up_at ? true : undefined}
            aria-describedby={followUpMessage ? followUpMessageId : undefined}
            className="h-8 w-auto bg-white"
          />
          <label htmlFor="discussion-follow-up-time" className="sr-only">
            Follow-up time ({zone})
          </label>
          <Input
            id="discussion-follow-up-time"
            type="time"
            value={time}
            onChange={(event) => changeFollowUp(date, event.target.value)}
            disabled={!followUp || submitting}
            aria-invalid={fieldErrors.follow_up_at ? true : undefined}
            aria-describedby={followUpMessage ? followUpMessageId : undefined}
            className="h-8 w-auto bg-white"
          />
          <span aria-hidden="true" className="text-xs font-semibold text-muted-foreground">
            {zone}
          </span>
        </div>

        <Button
          type="submit"
          disabled={submitting || incomplete}
          aria-busy={submitting}
          className="ml-auto bg-gray-900 text-white hover:bg-gray-800"
        >
          {submitting ? "Saving…" : "Save Note"}
        </Button>
      </div>

      {/* Always rendered: a live region must exist before its text changes. */}
      <p
        id={followUpMessageId}
        aria-live="polite"
        className={cn("text-sm empty:hidden", followUpMessage?.tone)}
      >
        {followUpMessage?.text}
      </p>
    </form>
  );
}
