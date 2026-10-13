# LeadFlow

LeadFlow is a lightweight, single-user CRM for managing leads, discussions,
and follow-ups.

> [!WARNING]
> LeadFlow has **no authentication**. Anyone who can reach a running instance
> can read and modify all of its data. Run it only on your own machine and
> **never expose it to the public internet**. The Docker setup is for local
> development only and is not production-hardened.

## Project Status

**Stage 1 — project foundation.** The frontend, backend, database, and Docker
Compose environment are set up, with a single `GET /api/health` endpoint.
No CRM features (leads, discussions, follow-ups) exist yet.

## Architecture

```
Browser ──► Next.js client app ──► FastAPI (/api/*) ──► PostgreSQL
```

- The **browser calls FastAPI directly** using `NEXT_PUBLIC_API_URL`. Next.js
  serves the UI only; it has no API routes and does not proxy or fetch CRM
  data on the server.
- **FastAPI** owns all business logic and data access, using synchronous
  SQLAlchemy 2.0 sessions with psycopg 3.
- **CORS** is restricted to the explicit origins in `CORS_ORIGINS`;
  wildcards are rejected at startup.

## Tech Stack

| Area              | Technology                                                        |
| ----------------- | ----------------------------------------------------------------- |
| Frontend          | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, shadcn/ui, date-fns, date-fns-tz |
| Backend           | Python 3.12, FastAPI, Pydantic v2, pydantic-settings, Uvicorn     |
| Database          | PostgreSQL 17, SQLAlchemy 2.0 (sync), psycopg 3, Alembic          |
| Tooling           | uv, Ruff, pytest, ESLint, Docker Compose                          |

```
.
├── backend/             FastAPI app (uv project, uv.lock committed)
│   ├── app/             config.py, db.py, main.py
│   └── tests/
├── frontend/            Next.js App Router app
├── docker-compose.yml   db + backend + frontend for local development
└── .env.example         configuration template
```

## Prerequisites

- **Docker** with Compose v2 (Docker Desktop, or Colima on macOS)
- For running directly on the host:
  - **Node.js 20.9+** (developed with Node 24) and npm
  - **Python 3.12**
  - **[uv](https://docs.astral.sh/uv/getting-started/installation/)**

## Configuration

Create your local `.env` from the template. It is git-ignored, so never
commit it.

```bash
cp .env.example .env
```

| Variable                                         | Used by                                   |
| ------------------------------------------------ | ----------------------------------------- |
| `APP_TIMEZONE`                                   | Backend (default `Asia/Kolkata`; must be an exact, case-sensitive IANA name) |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Docker Compose PostgreSQL               |
| `DATABASE_URL`                                   | Backend when run **on the host** (must use `postgresql+psycopg://`, validated at startup) |
| `CORS_ORIGINS`                                   | Backend (comma-separated, at least one origin, no `*`) |
| `NEXT_PUBLIC_API_URL`                            | Frontend (URL the browser uses for the API) |

**Precedence.** The root `.env` supplies default values. Explicit environment
variables always override it:

- **Backend on the host:** a variable exported in your shell, such as
  `DATABASE_URL`, takes precedence over the same key in `.env`.
- **Docker Compose:** `${VAR}` placeholders in `docker-compose.yml` are filled
  from your shell environment first, then from the root `.env`. The backend
  container then receives only the values Compose passes to it.

If a setting seems to differ from `.env`, check whether it is exported in your
shell. `env | cut -d= -f1 | grep -E 'APP_TIMEZONE|DATABASE_URL|CORS_ORIGINS'`
lists the names of exported variables without printing their values. Then
`unset` the variable. Use `docker compose config` to see the values Compose resolves;
note that its output includes the database password.

**Host vs. Docker networking.** Only the database address differs:

| Backend runs…      | Connects to PostgreSQL at | Configured by                          |
| ------------------ | ------------------------- | -------------------------------------- |
| On the host        | `localhost:5433`          | `DATABASE_URL` in `.env`               |
| In Docker Compose  | `db:5432`                 | Built from `POSTGRES_*` in `docker-compose.yml` |

Compose publishes PostgreSQL on host port **5433** (not 5432) so it does not
clash with a PostgreSQL already installed on your machine. `NEXT_PUBLIC_API_URL`
is `http://localhost:8000` in both modes, because the browser always runs on
the host. If you change the `POSTGRES_*` values, update `DATABASE_URL` to match.

**Timezone.** `APP_TIMEZONE` is currently read and validated only by the
backend; an unknown IANA name stops startup. The frontend does not receive it
yet, so any date it rendered today would use the browser's local timezone.
When date/time formatting is implemented, the frontend will get the timezone
from the API at runtime, so that `APP_TIMEZONE` stays the single source of
truth. There is deliberately no separate `NEXT_PUBLIC_APP_TIMEZONE`, because
`NEXT_PUBLIC_*` values are baked into the browser bundle at build time and
could drift from the backend setting.

## Run with Docker Compose

```bash
docker compose up --build
```

- Frontend: <http://localhost:3000>
- API health: <http://localhost:8000/api/health>
- API docs: <http://localhost:8000/docs>

The backend waits for the PostgreSQL health check before starting. All ports
are bound to `127.0.0.1` only.

**Development containers.** Both Dockerfiles build development images. The
frontend image runs `next dev`. The backend image's default command runs
Uvicorn without reload, and Compose overrides it with `--reload`. Source
directories are bind-mounted for live changes. A production deployment would
need different images (for example `next build` + `next start`) and is out of
scope.

## Run Directly on the Host

Start only PostgreSQL in Docker, then run the apps locally:

```bash
docker compose up -d db
```

Backend (from `backend/`; reads the root `.env` automatically):

```bash
cd backend
uv sync --locked
uv run uvicorn app.main:app --reload --port 8000
```

Frontend (from `frontend/`, in a second terminal):

```bash
cd frontend
npm ci
npm run dev
```

The frontend defaults to `http://localhost:8000` for the API. To point it
elsewhere, set `NEXT_PUBLIC_API_URL` in `frontend/.env.local`, because Next.js
does not read the root `.env`.

## Checks

Frontend (from `frontend/`):

```bash
npm run lint
npm run typecheck
npm run build
```

Backend (from `backend/`):

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

The pytest suite does not need a running database. It covers the 503 health
response and settings validation.

## Verify the Health Endpoint

```bash
curl -i http://localhost:8000/api/health
```

| Situation                 | Status | Body                                               |
| ------------------------- | ------ | -------------------------------------------------- |
| API up, `SELECT 1` works  | `200`  | `{"status":"ok","database":"ok"}`                  |
| Database unreachable      | `503`  | `{"status":"unavailable","database":"unavailable"}` |

The database connection times out after 3 seconds, so the endpoint never
hangs. Error details and connection strings are never returned.

## Stop Services

```bash
docker compose down
```

This stops and removes the containers but **keeps** the database volume.

## Reset Local Database Data

> [!CAUTION]
> The following command **permanently deletes all local LeadFlow database
> data** stored in the `postgres_data` Docker volume. It cannot be undone.

```bash
docker compose down -v
```

## Current Limitations

- No authentication or authorization (see the warning above).
- No CRM features, database models, or migrations yet. Alembic is installed
  but not initialised.
- Docker images are for local development only.
- **Known `npm audit` findings:** 9 high-severity entries, all from one
  advisory, [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)
  (a denial-of-service bug in `braces` ≤ 3.0.3, triggered by deeply nested
  patterns). `braces` is pulled in through `fast-glob` → `micromatch` by
  `eslint-config-next` and by the `shadcn` CLI. Both are development tooling,
  and `npm audit --omit=dev` reports 0. No compatible patched release exists:
  `braces` 3.0.3 is the latest version, and npm's only suggested fix downgrades
  `eslint-config-next` and `shadcn` by major versions. Being dev-only reduces
  the exposure but does not make the advisory irrelevant: this tooling runs on
  developer machines and during builds. **Revisit when an upstream fix ships.**
