"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, getHealth, isAbortError } from "@/lib/api";

type Status = "checking" | "ok" | "database_unavailable" | "unreachable" | "error";

const LABELS: Record<Status, string> = {
  checking: "Checking…",
  ok: "API and database are available",
  database_unavailable: "API is running, but the database is unavailable",
  unreachable: "API is unreachable",
  error: "API returned an unexpected error",
};

async function checkHealth(signal?: AbortSignal): Promise<Status> {
  try {
    await getHealth(signal);
    return "ok";
  } catch (error) {
    if (isAbortError(error)) throw error;
    if (error instanceof ApiError) {
      if (error.code === "database_unavailable") return "database_unavailable";
      if (error.code === "network_error") return "unreachable";
    }
    return "error";
  }
}

export function ApiStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    const controller = new AbortController();
    checkHealth(controller.signal).then(setStatus, () => {
      // Aborted on unmount: nothing to update.
    });
    return () => controller.abort();
  }, []);

  function recheck() {
    setStatus("checking");
    checkHealth().then(setStatus);
  }

  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <span role="status" className="text-muted-foreground">
        {LABELS[status]}
      </span>
      <Button variant="outline" size="sm" onClick={recheck} disabled={status === "checking"}>
        Check again
      </Button>
    </div>
  );
}
