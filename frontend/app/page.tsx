import { ApiStatus } from "@/components/api-status";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-4 px-6 py-24">
      <h1 className="text-3xl font-semibold tracking-tight">LeadFlow</h1>
      <p className="text-muted-foreground">
        A lightweight, single-user CRM for managing leads, discussions, and
        follow-ups.
      </p>
      <ApiStatus />
    </main>
  );
}
