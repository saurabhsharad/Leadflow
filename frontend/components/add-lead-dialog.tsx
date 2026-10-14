"use client";

import { useRef, useState, type FormEvent, type RefObject } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, createLead } from "@/lib/api";
import type { LeadSummary } from "@/lib/types";
import { charCount } from "@/lib/utils";

// Same rules as the backend's LeadCreate (backend/app/schemas.py). The backend
// stays authoritative; these checks only give faster feedback.
const NAME_MAX = 120;
const COMPANY_MAX = 120;
const PHONE_MAX = 30;
const PHONE_PATTERN = /^[0-9+()\-\s]*$/;

type Field = "name" | "company" | "phone";
type Values = Record<Field, string>;
type FieldErrors = Partial<Record<Field, string>>;

const EMPTY: Values = { name: "", company: "", phone: "" };

const FIELDS: Field[] = ["name", "company", "phone"];

function validate(values: Values): FieldErrors {
  const errors: FieldErrors = {};
  const name = values.name.trim();
  if (!name) errors.name = "Name is required";
  else if (charCount(name) > NAME_MAX) errors.name = `Name must be at most ${NAME_MAX} characters`;
  if (charCount(values.company.trim()) > COMPANY_MAX) {
    errors.company = `Company must be at most ${COMPANY_MAX} characters`;
  }
  const phone = values.phone.trim();
  if (phone.length > PHONE_MAX) errors.phone = `Phone must be at most ${PHONE_MAX} characters`;
  else if (!PHONE_PATTERN.test(phone)) errors.phone = "Use only digits, spaces, +, -, ( and )";
  return errors;
}

function describeFailure(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "network_error") return "Server unavailable. Check your connection and try again.";
    return error.message;
  }
  return "Something went wrong. Please try again.";
}

interface AddLeadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (lead: LeadSummary) => void;
}

/**
 * "Add New Lead" (spec sections 4, 5 and 10): name required, company and phone
 * optional, no status (new leads always start as "new"). Errors keep the
 * dialog open with the typed values; it cannot be closed while saving.
 */
export function AddLeadDialog({ open, onOpenChange, onCreated }: AddLeadDialogProps) {
  const [values, setValues] = useState<Values>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const companyRef = useRef<HTMLInputElement>(null);
  const phoneRef = useRef<HTMLInputElement>(null);
  const refs = { name: nameRef, company: companyRef, phone: phoneRef };

  function reset() {
    setValues(EMPTY);
    setFieldErrors({});
    setFormError(null);
  }

  function handleOpenChange(next: boolean) {
    if (!next && submitting) return; // Esc, backdrop, ✕ and Cancel all wait for the save
    onOpenChange(next);
  }

  function update(field: Field, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    if (fieldErrors[field]) setFieldErrors((current) => ({ ...current, [field]: undefined }));
  }

  function showFieldErrors(errors: FieldErrors) {
    setFieldErrors(errors);
    const first = FIELDS.find((field) => errors[field]);
    if (first) refs[first].current?.focus();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;

    const clientErrors = validate(values);
    if (Object.keys(clientErrors).length > 0) {
      setFormError(null);
      showFieldErrors(clientErrors);
      return;
    }

    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);
    try {
      const lead = await createLead({
        name: values.name.trim(),
        company: values.company.trim() || null,
        phone: values.phone.trim() || null,
      });
      onOpenChange(false); // the form resets once the close animation finishes
      onCreated(lead);
    } catch (error) {
      // The dialog stays open and keeps what was typed.
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
      if (Object.keys(serverFieldErrors).length === 0 || otherErrors) {
        setFormError(describeFailure(error));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={handleOpenChange}
      onOpenChangeComplete={(isOpen) => {
        if (!isOpen) reset(); // after closing, so the form never visibly blanks
      }}
    >
      <DialogContent className="sm:max-w-[450px]" initialFocus={nameRef}>
        <form noValidate onSubmit={handleSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle className="text-lg font-semibold">Add New Lead</DialogTitle>
            <DialogDescription className="sr-only">
              Full name is required. Company and phone are optional.
            </DialogDescription>
          </DialogHeader>

          {formError ? (
            <p
              role="alert"
              className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
            >
              {formError}
            </p>
          ) : null}

          <LeadField
            id="lead-name"
            label="Full Name"
            required
            placeholder="e.g., John Doe"
            autoComplete="name"
            value={values.name}
            error={fieldErrors.name}
            onChange={(value) => update("name", value)}
            inputRef={nameRef}
          />
          <LeadField
            id="lead-company"
            label="Company"
            placeholder="e.g., Stark Industries"
            autoComplete="organization"
            value={values.company}
            error={fieldErrors.company}
            onChange={(value) => update("company", value)}
            inputRef={companyRef}
          />
          <LeadField
            id="lead-phone"
            label="Phone"
            type="tel"
            placeholder="e.g., 555-0123"
            autoComplete="tel"
            value={values.phone}
            error={fieldErrors.phone}
            onChange={(value) => update("phone", value)}
            inputRef={phoneRef}
          />

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => handleOpenChange(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={submitting}
              aria-busy={submitting}
              className="bg-blue-600 text-white hover:bg-blue-700"
            >
              {submitting ? "Saving…" : "Save Lead"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

interface LeadFieldProps {
  id: string;
  label: string;
  required?: boolean;
  type?: string;
  placeholder: string;
  autoComplete: string;
  value: string;
  error: string | undefined;
  onChange: (value: string) => void;
  inputRef: RefObject<HTMLInputElement | null>;
}

function LeadField({
  id,
  label,
  required = false,
  type = "text",
  placeholder,
  autoComplete,
  value,
  error,
  onChange,
  inputRef,
}: LeadFieldProps) {
  const errorId = `${id}-error`;
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>
        {label}
        {required ? (
          <span className="text-red-600" aria-hidden="true">
            *
          </span>
        ) : (
          <span className="font-normal text-muted-foreground">(Optional)</span>
        )}
      </Label>
      <Input
        ref={inputRef}
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className="h-9"
      />
      {error ? (
        <p id={errorId} className="text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}
