# ADR-010: Backend Authentication and Production Persistence

**Status:** Accepted
**Date:** 2026-06-11

## Context

Picnix currently runs as a Streamlit + LangGraph app with a local-first runtime. The app uses LangGraph `MemorySaver` for checkpointing, which preserves interrupt/resume state only inside the current process. That was acceptable for the single-user MVP, but it does not survive restarts and is not suitable for multiple user accounts.

The current Docker Compose deployment runs the Picnix app beside self-hosted Phoenix for observability. The next milestone adds account persistence, authenticated Streamlit sessions, a strict 5-completed-trip trial limit per account, and durable LangGraph checkpoint state while preserving the existing `interrupt_before=["n4_route", "n8_editor"]` flow.

## Decision

Use PostgreSQL 15 as the production persistence layer. Docker Compose will add a third service named `db` using the `postgres:15` image and a named `postgres-data` volume.

Use `streamlit-authenticator` in `app.py` for registration, login, logout, and authenticated Streamlit session handling. User records live in PostgreSQL; passwords are stored only as hashes.

Replace LangGraph `MemorySaver` with LangGraph's native PostgreSQL checkpointer (`PostgresSaver` or the connection-pool-backed equivalent). The checkpointer will use a `psycopg` connection pool configured from `DATABASE_URL`. App startup will initialize both Picnix-owned tables and the LangGraph checkpoint schema if they do not already exist.

Keep FastAPI out of this milestone. Authentication, trial enforcement, and checkpoint persistence stay inside the Streamlit app boundary until a separate API layer is explicitly scheduled.

## Relational Schema

Primary user table:

```sql
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    verification_token UUID,
    trips_planned INTEGER NOT NULL DEFAULT 0
        CHECK (trips_planned >= 0 AND trips_planned <= 5),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);
```

Completion ledger used to make trial counting idempotent:

```sql
CREATE TABLE IF NOT EXISTS trip_runs (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    thread_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    count_applied BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
```

`users` is the account source of truth. `is_verified` and `verification_token` were added by ADR-011 after this persistence decision so graph execution can require verified email. `trip_runs` exists because Streamlit reruns and browser refreshes can revisit the same completed graph thread. Counting must be tied to a unique graph `thread_id`, not to a UI render.

## Trial Gatekeeper

Before starting or resuming graph execution for trip planning, the authenticated username is checked in PostgreSQL. If `users.is_verified = FALSE`, graph execution is blocked until the user verifies email through the ADR-011 Resend flow. If `users.trips_planned >= 5`, graph execution is blocked and Streamlit renders a clean "Limit Reached" UI.

The counter increments only when the graph successfully completes N7 and parks at the `n8_editor` interrupt. The post-execution update must run in one database transaction:

1. Mark the current `thread_id` completed in `trip_runs` if it has not already been completed.
2. Increment `users.trips_planned` only when the completion record transitions from uncounted to counted.
3. Guard the user update with `WHERE trips_planned < 5`.

This makes the trial limit strict and prevents double-counting the same completed trip after Streamlit reruns.

## Options Considered

- **Keep `MemorySaver`:** Rejected. It is process-local and loses all graph state on restart.
- **Store users in a YAML file for `streamlit-authenticator`:** Rejected. Account state and trial counters need transactional writes.
- **Add FastAPI now:** Rejected for this milestone. The product still runs as Streamlit, and adding an API layer would widen the scope before persistence and auth are stable.
- **PostgreSQL + `streamlit-authenticator` + LangGraph PostgreSQL checkpointing:** Chosen. One database supports account records, trial enforcement, and durable graph checkpoints.

## Consequences

- `DATABASE_URL` becomes the persistence configuration source, with a local fallback for development.
- Docker Compose becomes a three-service topology: `app`, `phoenix`, and `db`.
- The app container must wait for Postgres health before booting.
- LangGraph checkpoint tables are created by the LangGraph checkpointer setup routine, not handwritten Picnix DDL.
- User passwords never appear in source-controlled files or `.env.example`.
- Trial-limit correctness depends on idempotent completion recording after N7.
