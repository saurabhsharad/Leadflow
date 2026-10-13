"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { API_BASE_URL } from "@/lib/config";

type Status = "checking" | "ok" | "unavailable" | "unreachable";

const LABELS: Record<Status, string> = {
  checking: "Checking…",
  ok: "API and database are available",
  unavailable: "API is running, but the database is unavailable",
  unreachable: "API is unreachable",
};

// Calls GET /api/health directly from the browser (no Next.js server hop).
async function fetchHealth(): Promise<Status> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/health`, { cache: "no-store" });
    return res.ok ? "ok" : "unavailable";
  } catch {
    return "unreachable";
  }
}

export function ApiStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    let ignore = false;
    fetchHealth().then((result) => {
      if (!ignore) setStatus(result);
    });
    return () => {
      ignore = true;
    };
  }, []);

  function recheck() {
    setStatus("checking");
    fetchHealth().then(setStatus);
  }

  return (
    <div className="flex items-center gap-3 text-sm">
      <span role="status" className="text-muted-foreground">
        {LABELS[status]}
      </span>
      <Button
        variant="outline"
        size="sm"
        onClick={recheck}
        disabled={status === "checking"}
      >
        Check again
      </Button>
    </div>
  );
}
