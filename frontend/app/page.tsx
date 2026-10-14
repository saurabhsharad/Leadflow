import { ApiStatus } from "@/components/api-status";

// Placeholder until the dashboard stage: the shell plus a live API check.
export default function Home() {
  return (
    <section aria-labelledby="page-title" className="flex flex-col gap-3">
      <h1 id="page-title" className="text-2xl font-semibold tracking-tight">
        Leads
      </h1>
      <p className="text-muted-foreground">
        A lightweight, single-user CRM for managing leads, discussions, and follow-ups.
      </p>
      <ApiStatus />
    </section>
  );
}
