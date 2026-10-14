import Link from "next/link";

import { SiteHeader } from "@/components/site-header";

// Pages render the header and <main id="content"> themselves (see layout.tsx),
// so this page provides the skip link's target too.
export default function NotFound() {
  return (
    <>
      <SiteHeader />
      <main id="content" className="mx-auto w-full max-w-5xl flex-1 px-4 py-6 sm:px-6 sm:py-8">
        <section aria-labelledby="not-found-title" className="flex flex-col items-start gap-3">
          <h1 id="not-found-title" className="text-2xl font-semibold tracking-tight">
            Page not found
          </h1>
          <p className="text-muted-foreground">
            The page you are looking for does not exist or has moved.
          </p>
          <Link
            href="/"
            className="rounded-md text-sm font-medium text-blue-700 underline underline-offset-4 hover:text-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            Go to the lead dashboard
          </Link>
        </section>
      </main>
    </>
  );
}
