# LeadFlow

LeadFlow is a lightweight, single-user CRM for managing leads, discussions,
and follow-ups.

## Planned Technology Stack

| Area              | Technology                                              |
| ----------------- | ------------------------------------------------------- |
| Frontend          | Next.js (App Router), React, TypeScript, Tailwind CSS, shadcn/ui |
| Backend           | Python, FastAPI, Pydantic v2                            |
| Database          | PostgreSQL                                              |
| ORM               | SQLAlchemy 2.0 (synchronous sessions)                   |
| Migrations        | Alembic                                                 |
| Testing           | pytest, Playwright                                      |
| Local development | Docker Compose                                          |

## Project Status

**Early setup.** The repository contains only initial configuration files.
No frontend, backend, database, or Docker setup has been implemented yet, so
there are no setup or run instructions at this stage.

## Security Notice

> [!WARNING]
> LeadFlow is planned as a single-user demo **without authentication**.
> Anyone who can reach a running instance can read and modify all of its data.
> Run it only on your local machine or a trusted private network.
> **Do not expose it to the public internet.**

Never commit real credentials. Use `.env.example` as a template for a local,
untracked `.env` file.
