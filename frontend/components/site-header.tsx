import { TrendingUp } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

/** White header with the LeadFlow wordmark; `actions` sits on the right. */
export function SiteHeader({ actions }: { actions?: ReactNode }) {
  return (
    <header className="border-b bg-white">
      <div className="mx-auto flex h-16 w-full max-w-5xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2 rounded-md text-lg font-semibold tracking-tight">
          <TrendingUp className="size-6 text-blue-600" aria-hidden="true" />
          LeadFlow
        </Link>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}
