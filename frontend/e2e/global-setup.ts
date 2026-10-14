// Runs once before the specs: refuse anything but the isolated E2E stack, then
// reset its demo data (the specification runs the specs "after a seed reset").

import { execFileSync } from "node:child_process";
import path from "node:path";

import { API_URL, BASE_URL, E2E_PROJECT } from "./env";

// The production and development stacks' ports: their data must never be touched.
const PROTECTED_PORTS = new Set(["3000", "8000"]);
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const COMPOSE = [
  "compose",
  "-p",
  E2E_PROJECT,
  "-f",
  path.join(REPO_ROOT, "docker-compose.yml"),
  "-f",
  path.join(REPO_ROOT, "docker-compose.e2e.yml"),
];

function portOf(url: string): string {
  const parsed = new URL(url);
  return parsed.port || (parsed.protocol === "https:" ? "443" : "80");
}

/** `docker compose` for the E2E project only (arguments, no shell). */
function compose(args: string[]): string {
  return execFileSync("docker", [...COMPOSE, ...args], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

export default async function globalSetup(): Promise<void> {
  for (const url of [BASE_URL, API_URL]) {
    if (PROTECTED_PORTS.has(portOf(url))) {
      throw new Error(
        `Refusing to run end-to-end tests against ${url}: ports 3000 and 8000 belong to ` +
          "the production and development stacks. Use the leadflow-e2e stack (3001/8001).",
      );
    }
  }

  // The API under test must be the leadflow-e2e backend container itself.
  const published = compose(["port", "backend", "8000"]);
  if (!published.endsWith(`:${portOf(API_URL)}`)) {
    throw new Error(
      `${E2E_PROJECT} publishes its backend on ${published || "nothing"}, not on ${API_URL}. ` +
        "Start it with: docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build",
    );
  }
  const health = await fetch(`${API_URL}/api/health`);
  if (!health.ok) throw new Error(`${API_URL}/api/health returned HTTP ${health.status}`);

  // Seed reset inside the E2E backend container. It confirms the database name
  // that container's own DATABASE_URL points to (db:5432 on the E2E network).
  const database = compose([
    "exec",
    "-T",
    "backend",
    "python",
    "-c",
    "import os; from sqlalchemy.engine import make_url; "
      + "print(make_url(os.environ['DATABASE_URL']).database)",
  ]);
  const output = compose([
    "exec",
    "-T",
    "backend",
    "python",
    "-m",
    "scripts.seed",
    "--reset",
    "--yes",
    "--confirm-database",
    database,
  ]);
  console.log(`[${E2E_PROJECT}] ${output.replaceAll("\n", `\n[${E2E_PROJECT}] `)}`);
}
