# LeadFlow

LeadFlow is a lightweight, single-user CRM for managing leads, discussions,
and follow-ups.

> [!WARNING]
> LeadFlow has **no authentication**. Anyone who can reach a running instance
> can read and modify all of its data. Run it only on your own machine and
> **never expose it to the public internet**. The Docker setup is for local
> development only and is not production-hardened.

## Project Status

**Stage 2 — database schema.** The frontend, backend, database, and Docker
Compose environment are set up, with a single `GET /api/health` endpoint. The
`leads` and `discussions` tables exist as SQLAlchemy models and an Alembic
migration. There are no CRM API endpoints or UI features yet.

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
│   ├── app/             config.py, db.py, main.py, models.py
│   ├── alembic/         migration environment and versions/
│   └── tests/
├── frontend/            Next.js App Router app
├── docker/postgres/     creates the leadflow_test database on first start
├── docker-compose.yml       production-style stack (built images, demo data)
├── docker-compose.dev.yml   development stack (live reload)
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
| `DATABASE_URL`                                   | Backend and Alembic when run **on the host** (must use `postgresql+psycopg://`, validated at startup) |
| `TEST_DATABASE_URL`                              | Backend PostgreSQL tests only (database name must end in `_test`) |
| `CORS_ORIGINS`                                   | Backend (comma-separated, at least one origin, no `*`) |
| `SEED_DEMO_DATA`                                 | `python -m scripts.seed --auto` only (default `false`; see Demo Data) |
| `NEXT_PUBLIC_API_URL`                            | Frontend (URL the browser uses for the API) |
| `NEXT_PUBLIC_APP_TIMEZONE`                       | Frontend display timezone; set by Compose from `APP_TIMEZONE` |

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
| In Docker Compose  | `db:5432`                 | Built from `POSTGRES_*` in the Compose files |

Compose publishes PostgreSQL on host port **5433** (not 5432) so it does not
clash with a PostgreSQL already installed on your machine. `NEXT_PUBLIC_API_URL`
is `http://localhost:8000` in both modes, because the browser always runs on
the host. If you change the `POSTGRES_*` values, update `DATABASE_URL` to match.

**Timezone.** `APP_TIMEZONE` decides what "today" means. The backend
validates it at startup (an unknown IANA name stops it) and uses it to classify
follow-ups. The frontend formats every date and time in the same timezone,
never the browser's own, using `NEXT_PUBLIC_APP_TIMEZONE`:

- Docker Compose sets `NEXT_PUBLIC_APP_TIMEZONE` from `APP_TIMEZONE`, so one
  value configures both services.
- For a frontend run on the host, set `NEXT_PUBLIC_APP_TIMEZONE` in
  `frontend/.env.local` to match `APP_TIMEZONE`. It defaults to `Asia/Kolkata`.
- Like every `NEXT_PUBLIC_*` value, it is baked into the browser bundle at build
  time, so changing it means rebuilding the frontend.

## Run with Docker Compose

Two Compose files read the same root `.env`:

| File | Stack | Project and database volume | Start it with |
| ---- | ----- | --------------------------- | ------------- |
| `docker-compose.yml` | Production-style demo: built images, migrations and demo data on start | `leadflow-prod`, `leadflow-prod_postgres_data` | `docker compose up --build` |
| `docker-compose.dev.yml` | Development: `next dev`, Uvicorn `--reload`, source bind-mounted | `leadflow`, `leadflow_postgres_data` | `docker compose -f docker-compose.dev.yml up --build` |

- Frontend: <http://localhost:3000>
- API health: <http://localhost:8000/api/health>
- API docs: <http://localhost:8000/docs>

Each stack has its own database volume, so neither sees the other's data. Both
use ports 3000 and 8000, so **run only one at a time**. All ports are bound to
`127.0.0.1` only.

**Production stack.** The backend waits for the PostgreSQL health check, then
its start-up script (`backend/docker-entrypoint.sh`):

1. applies migrations (`alembic upgrade head`);
2. runs `python -m scripts.seed --auto` with `SEED_DEMO_DATA=true`, which inserts
   the demo data only into an empty database (in practice, the first start) and
   never resets or changes existing rows;
3. starts Uvicorn.

The frontend starts once `/api/health` reports healthy. It is a `next build`
standalone server; `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_APP_TIMEZONE` (taken
from `APP_TIMEZONE`) are **build arguments** baked into the bundle, so change
them with `docker compose up --build`. Both application containers run as
non-root users.

**Production database port.** PostgreSQL is published on `127.0.0.1:5432` by
default, matching the specification. If that port is already in use (for
example by a PostgreSQL installed on your machine), the database container fails
to start. Leave the other service as it is and choose another host port instead,
by adding this line to your local `.env` before starting the stack:

```bash
POSTGRES_PROD_HOST_PORT=5434
```

This changes only the host side. The backend still connects to `db:5432` inside
the Compose network, and the development stack's database stays on port `5433`.

**Development stack.** `backend/Dockerfile.dev` and `frontend/Dockerfile.dev`
build development images: the frontend runs `next dev`, and Compose runs the
backend with `--reload`. Source directories are bind-mounted for live changes.
This stack does not run migrations; apply them from the host (see Database
Migrations). PostgreSQL is published on `127.0.0.1:5433`.

## Run Directly on the Host

Start only PostgreSQL in Docker, then run the apps locally:

```bash
docker compose -f docker-compose.dev.yml up -d db
```

Backend (from `backend/`; reads the root `.env` automatically):

```bash
cd backend
uv sync --locked
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

Frontend (from `frontend/`, in a second terminal):

```bash
cd frontend
npm ci
npm run dev
```

The frontend reads the API location from `NEXT_PUBLIC_API_URL`, the URL the
**browser** uses to reach FastAPI (for example `http://localhost:8000`). Set it
in `frontend/.env.local` or the environment, because Next.js does not read the
root `.env`.

- `npm run dev` falls back to `http://localhost:8000` when it is unset.
- `npm run build` has no fallback: the value is baked into the browser bundle at
  build time, and API calls fail with a configuration error if it was unset.
- It is public by design. Never put credentials or backend secrets in any
  `NEXT_PUBLIC_*` variable.

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

Most tests need the dedicated **`leadflow_test`** PostgreSQL database, set via
`TEST_DATABASE_URL`. They drop and recreate its tables, so the fixture refuses
any database whose name does not end in `_test`. They never use `DATABASE_URL`.

- **New database volume:** `docker compose -f docker-compose.dev.yml up -d db` creates `leadflow_test`
  automatically via `docker/postgres/01-create-test-database.sql`.
- **Volume created before this script existed:** Postgres runs init scripts
  only on an empty volume, so create the database once. This adds an empty
  database and does not touch existing data:

  ```bash
  docker compose -f docker-compose.dev.yml exec db createdb -U leadflow leadflow_test
  ```

If `TEST_DATABASE_URL` is missing or PostgreSQL is not reachable, the database
tests **fail** with an explanation; they are never silently skipped. The
settings and 503 health tests run without a database.

## Database Migrations

The schema is managed by Alembic. Commands run from `backend/` and use
`DATABASE_URL` (from your environment or the root `.env`), so with the Compose
database they target `leadflow` on `localhost:5433`.

```bash
cd backend
uv run alembic upgrade head
```

Inspect the state without changing anything:

```bash
uv run alembic current
uv run alembic history
uv run alembic check
```

`alembic check` reports whether the models and the database schema differ.

> [!CAUTION]
> Downgrading drops the `leads` and `discussions` tables and **all their
> data**. Check which database `DATABASE_URL` points to before running it.

```bash
uv run alembic downgrade base
```

The development backend container does not run migrations, so run
`uv run alembic upgrade head` from the host after the database starts. (The
production stack's backend applies them at start-up.)

## Demo Data

`backend/scripts/seed.py` inserts eight fictional leads covering all six
statuses and every follow-up state (later today, earlier today and overdue,
overdue from yesterday, tomorrow, later, none), with times relative to now in
`APP_TIMEZONE`. Run it from `backend/` after migrating:

```bash
uv run python -m scripts.seed
```

It inserts **only when the `leads` and `discussions` tables are both empty**;
otherwise it changes nothing. `--auto` does the same, but only when
`SEED_DEMO_DATA=true`.

The demo times are relative to when they were inserted, so on a later day
"today" no longer matches. To refresh them, reset the data:

> [!CAUTION]
> `--reset` **permanently deletes every lead and discussion** in the target
> database before inserting the demo data. It requires `--yes`, the database's
> name in `--confirm-database`, and `DATABASE_URL` exported in your shell (a
> value only in `.env` is refused). The script prints the target host and
> database (never credentials) before writing.
>
> **Before running it, check that `DATABASE_URL` points to the database whose
> data you mean to replace**, not one holding data you want to keep. Replace
> both `<demo-database>` placeholders below with that database's name.

```bash
export DATABASE_URL='postgresql+psycopg://<user>:<password>@<host>:<port>/<demo-database>'
uv run python -m scripts.seed --reset --yes --confirm-database <demo-database>
```

## Verify the Health Endpoint

```bash
curl -i http://localhost:8000/api/health
```

| Situation                 | Status | Body                                               |
| ------------------------- | ------ | -------------------------------------------------- |
| API up, `SELECT 1` works  | `200`  | `{"status":"ok","database":"ok"}`                  |
| Database unreachable      | `503`  | `{"detail":"Database unavailable","code":"database_unavailable","errors":[]}` |

The database connection times out after 3 seconds, so the endpoint never
hangs. Error details and connection strings are never returned.

## API Errors

Every non-2xx response uses one envelope:

```json
{"detail": "Validation failed", "code": "validation_error",
 "errors": [{"field": "name", "message": "Name is required"}]}
```

| Status | `code`                 | When                                              |
| ------ | ---------------------- | ------------------------------------------------- |
| 404    | `not_found`            | Unknown route                                     |
| 404    | `lead_not_found`       | A lead id that does not exist                     |
| 405    | `method_not_allowed`   | Unsupported HTTP method (the `Allow` header is kept) |
| 422    | `validation_error`     | Invalid request; `errors` lists each problem      |
| 500    | `internal_error`       | Any unexpected error (details are logged server-side only) |
| 503    | `database_unavailable` | No database connection could be obtained (see below), the connection dropped, or the pool timed out |

`errors` is empty except for 422. Each item has a `field` (for example
`name`, or `items.0.note` for nested values) and a `message`. `field` is
`null` when the problem concerns the whole body, such as an empty update or
malformed JSON.

**503 also covers configuration problems.** Any failure to *establish* a
database connection returns 503 `database_unavailable`, including a wrong
password, an unknown database name, or a TLS error, not only a stopped server.
The PostgreSQL driver reports all of these the same way, before any SQL runs.
If the API returns 503 while PostgreSQL is running, check `DATABASE_URL`.
Errors raised by an already-open connection (for example a constraint
violation) return 500 `internal_error`, unless they are connection errors
(SQLSTATE class `08`, or `57P01`–`57P03`).

## Stop Services

```bash
docker compose down                              # production stack
docker compose -f docker-compose.dev.yml down    # development stack
```

This stops and removes that stack's containers but **keeps** its database volume.

## Reset Local Database Data

> [!CAUTION]
> The following command **permanently deletes all development database data**
> stored in the `leadflow_postgres_data` Docker volume. It cannot be undone.
> Without `-f docker-compose.dev.yml` it deletes the production stack's volume
> (`leadflow-prod_postgres_data`) instead.

```bash
docker compose -f docker-compose.dev.yml down -v
```

## Current Limitations

- No authentication or authorization (see the warning above).
- No CRM API endpoints or UI features yet; only the database schema exists.
- Migrations are run from the host; the backend container does not apply them.
- The "not blank" checks reject values made only of ASCII whitespace (spaces,
  tabs, newlines). Other Unicode spaces, such as a non-breaking space, are
  not treated as blank by PostgreSQL; the API will trim input before saving.
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
