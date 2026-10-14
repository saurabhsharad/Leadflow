import { Search } from "lucide-react";

import { STATUS_OPTIONS } from "@/lib/statuses";
import type { LeadStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

interface LeadFiltersProps {
  /** undefined means "All". */
  status: LeadStatus | undefined;
  onStatusChange: (status: LeadStatus | undefined) => void;
  search: string;
  onSearchChange: (search: string) => void;
}

const PILLS: { value: LeadStatus | undefined; label: string }[] = [
  { value: undefined, label: "All" },
  ...STATUS_OPTIONS,
];

/** Status pills (aria-pressed) and the name search box (spec section 5). */
export function LeadFilters({ status, onStatusChange, search, onSearchChange }: LeadFiltersProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div role="group" aria-labelledby="status-filter-label" className="flex flex-wrap items-center gap-2">
        <span
          id="status-filter-label"
          className="text-xs font-semibold uppercase tracking-widest text-muted-foreground"
        >
          Filters:
        </span>
        {PILLS.map((pill) => {
          const selected = pill.value === status;
          return (
            <button
              key={pill.label}
              type="button"
              aria-pressed={selected}
              onClick={() => onStatusChange(pill.value)}
              className={cn(
                "rounded-full border px-3 py-1 text-sm font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2",
                selected
                  ? "border-gray-900 bg-gray-900 text-white"
                  : "border-gray-200 bg-white text-gray-700 hover:bg-gray-100",
              )}
            >
              {pill.label}
            </button>
          );
        })}
      </div>

      <div className="relative w-full sm:w-56 sm:shrink-0">
        <label htmlFor="lead-search" className="sr-only">
          Search leads by name
        </label>
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <input
          id="lead-search"
          type="search"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Search by name"
          maxLength={100}
          autoComplete="off"
          className="h-9 w-full rounded-md border border-gray-200 bg-white pl-8 pr-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        />
      </div>
    </div>
  );
}
