# Picnix 🧺

**Tell Picnix you're free on Saturday. Get back a verified, mapped, minute-by-minute day trip — and an AI auditor that can explain every decision the planner made.**

*Built for the Google Cloud Rapid Agent Hackathon — Arize track. Powered by Gemini on Vertex AI, orchestrated with LangGraph, observed end-to-end with Arize Phoenix.*

---

## The problem

Everyone has had this Saturday: a free day, a full tank, and forty browser tabs of "places to visit near me" — half of them closed today, a third too far to reach, and none of them assembled into an actual plan. Generic chatbots make it worse: they'll cheerfully invent a waterfall that doesn't exist and tell you a 3-hour drive takes 45 minutes.

Picnix is an agent, not a chatbot. It doesn't *describe* a trip — it **builds one**, checks its own work against live Google Maps data, and hands you a plan you can drive.

## What it actually does

One short conversation in, one complete trip out:

1. **Understands you** — a Gemini intent agent extracts where you're starting, how long you have, who's coming, and what you're into (max 3 questions, then it makes smart assumptions).
2. **Finds real places** — computes your reachable area from your vehicle and time budget, then pulls live candidates from Google Places.
3. **Verifies before suggesting** — every candidate is validated against real opening hours, permanent-closure flags, known access issues, and *actual* Routes API travel times. You are never shown a place the agent can't prove you can visit.
4. **Keeps you in control** — the graph pauses at a human-in-the-loop interrupt; you pick 1–3 stops from a validated gallery before any route is built.
5. **Builds the itinerary** — one multi-waypoint round-trip route with real ETAs, LLM-reasoned dwell times per stop, and meal planning that searches for food *along your actual route geometry* (or tells you honestly to pack a parcel).
6. **Audits itself** — a structural + semantic validator (Gemini) checks the plan before any prose is written; the composer then writes the itinerary with an inline **claim audit**, stripping any sentence it can't trace back to verified data. Hallucinations don't survive to the user.
7. **Takes edits in plain English** — "swap the beach for the museum and leave at 9" re-plans the route through the same validation gauntlet. Then it parks and waits for your next edit.
8. **Ships it** — interactive Mapbox route map, timeline, and a one-tap **Open in Google Maps** deep link for turn-by-turn navigation.

## The Arize superpower: an agent that audits the agent 🔍

Planning agents fail in interesting ways — a destination gets dropped, a validator routes back, a retry fires. Most projects bolt on a dashboard. Picnix ships a **Trip Auditor**: a second Gemini agent whose entire tool surface is **Arize Phoenix trace data**, integrated through the official **Arize Phoenix MCP server** (`@arizeai/phoenix-mcp`).

Ask it things like *"Why did my last plan drop a destination?"* or *"Summarize the validation failures across my recent trips"* — and it answers by reading the actual OpenInference spans of your runs.

What makes it more than a demo:

- **Full-fidelity tracing** — every LangGraph node, Gemini call, and tool invocation is auto-instrumented via OpenInference and streamed to a self-hosted Phoenix collector (ADR-009).
- **Real MCP integration** — admins get the complete Phoenix MCP toolset over stdio, giving Gemini org-wide trace superpowers.
- **Security as architecture, not prompt** — regular users get exactly two database-validated tools, scoped server-side to *their own* trips via `session.id` span attributes. The privacy boundary is the tool surface itself: prompt injection cannot widen it (ADR-013).
- **Closed loop** — the same traces that power the auditor power our own debugging. This repo's bugs were found in Phoenix before users ever saw them.

## Architecture at a glance

![Picnix LangGraph](docs/graph.png)

An 8-node LangGraph state machine with two human-in-the-loop interrupts and a self-healing error path:

| Node | Role | Brains |
|---|---|---|
| N1 | Intent collector — typed clarification prompts | Gemini 3.1 Pro |
| N2 | Reachable-area + candidate discovery | Google Geocoding + Places |
| N3 | Destination validator — hours, closure, real travel time | Google Places + Routes |
| ⏸ | **Human interrupt** — pick your stops | You |
| N4 | Route builder — waypoints, ETAs, dwell-time reasoning, food | Routes API + Gemini 3.1 Pro |
| N5 | Structured validator — Python checks + semantic LLM pass; rejects bad plans *before* prose | Gemini 3.1 Pro |
| N6 | Composer — itinerary with inline claim audit; unverified claims stripped | Gemini 2.5 Flash |
| N7 | GeoJSON formatter for the Mapbox map | Pure Python |
| N8 | Natural-language plan editor — parks until your next edit | Gemini 3.1 Pro |

When N5 finds an unfixable error, it removes the unplannable stop, tells the user why, and re-routes the survivors — the graph never silently swaps your destination and never shows you a broken plan.

## Built like a product, not a prototype

- **Gemini 3.1 Pro** (reasoning slots) + **Gemini 2.5 Flash** (prose) on **Vertex AI**, with centralized Tenacity retry/backoff for quota resilience.
- **PostgreSQL-backed LangGraph checkpointing** — interrupted plans survive restarts; every session is a durable thread.
- **Real accounts** — bcrypt auth, Resend email verification, and a trial gatekeeper, all enforced server-side.
- **One-command deploy** — Docker Compose stack (app + Phoenix + Postgres) running on a GCP Compute Engine VM.
- **175 tests across 20 modules**, 13 Architecture Decision Records, and a region-agnostic design that works anywhere Google Maps does.

---

## Start The Project

From the repository root:

```bash
uv run streamlit run app.py
```

PostgreSQL must be reachable at `DATABASE_URL`. For the compose deployment, the `db` service provides this automatically; for local non-compose runs, start a local Postgres matching `.env.example` or set `DATABASE_URL` to your database.

Then open the local URL Streamlit prints, usually:

```text
http://localhost:8501
```

To run on a specific port:

```bash
uv run streamlit run app.py --server.port 8501
```

Stop the server with `Ctrl+C` in the terminal that is running Streamlit.

## Setup

Install `uv` and use Python 3.13 or newer.

Create a local `.env` file from the template:

```bash
cp .env.example .env
```

Fill these keys:

```text
GOOGLE_MAPS_API_KEY=
MAPBOX_TOKEN=
GOOGLE_CLOUD_PROJECT=
GOOGLE_CLOUD_LOCATION=<your-vertex-ai-region>  # e.g. us-central1; use "global" for gemini-3.1-pro-preview
GOOGLE_APPLICATION_CREDENTIALS=
LLM_RETRY_ATTEMPTS=5
LLM_RETRY_BACKOFF_MIN_SECONDS=1
LLM_RETRY_BACKOFF_MAX_SECONDS=30
RESEND_API_KEY=
RESEND_FROM_EMAIL="Picnix <onboarding@resend.dev>"
APP_BASE_URL=http://localhost:8501
# Optional: Trip Auditor access — comma-separated usernames get full-MCP admin scope
ADMIN_USERNAMES=
```

For local Vertex AI auth, prefer Application Default Credentials and leave `GOOGLE_APPLICATION_CREDENTIALS` blank unless you are using a service account JSON:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project <GOOGLE_CLOUD_PROJECT>
```

## Observability

Phoenix tracing is available but disabled by default. The app includes the Phoenix exporter by default and the Phoenix server as an optional `uv` extra for local demos.

In one terminal, start the local Phoenix dashboard:

```bash
PHOENIX_WORKING_DIR=.phoenix uv run --extra phoenix phoenix serve
```

The dashboard opens at:

```text
http://127.0.0.1:6006
```

In `.env`, enable tracing:

```text
OBSERVABILITY_ENABLED=true
ARIZE_PRODUCT=phoenix
ARIZE_PROJECT_NAME=picnix-local
```

Then run Picnix normally. Local Phoenix accepts traces on its default OTLP collector (`localhost:4317`), so `PHOENIX_COLLECTOR_ENDPOINT` can stay blank.
If tracing is enabled before Phoenix is reachable, the app keeps running and OpenTelemetry will log exporter warnings until a collector is available.

## Trip Auditor

The Streamlit sidebar exposes a second page, **Trip Auditor** — a standalone Gemini chat agent that answers questions about the Phoenix traces (e.g. "Why did my last plan drop a destination?"). Every logged-in user can audit their own trips only; ownership is enforced server-side against the `trip_runs` table. Usernames listed in `ADMIN_USERNAMES` instead get the full Arize Phoenix MCP toolset (`npx @arizeai/phoenix-mcp`) with org-wide access — Node.js is required for this mode and is preinstalled in the Docker image. The auditor reads `PHOENIX_BASE_URL` (defaults to `http://localhost:6006`; Compose sets `http://phoenix:6006`) and reuses `PHOENIX_API_KEY` when Phoenix auth is enabled. See `docs/adr/ADR-013-trip-auditor-mcp.md`.

## Docker Compose Deployment

The current deployment target is a single GCP Compute Engine VM running Docker Compose. The compose stack runs three services:

- `db` — PostgreSQL 15 with data persisted in the `postgres-data` volume.
- `phoenix` — self-hosted Phoenix UI and OTLP trace collector.
- `app` — Picnix Streamlit app, sending traces to `http://phoenix:6006/v1/traces` over the compose network.

Prepare `.env` on the VM before starting the stack:

```text
GOOGLE_MAPS_API_KEY=
MAPBOX_TOKEN=
GOOGLE_CLOUD_PROJECT=
GOOGLE_CLOUD_LOCATION=global
LLM_RETRY_ATTEMPTS=5
LLM_RETRY_BACKOFF_MIN_SECONDS=1
LLM_RETRY_BACKOFF_MAX_SECONDS=30
RESEND_API_KEY=
RESEND_FROM_EMAIL="Picnix <onboarding@resend.dev>"
APP_BASE_URL=http://<VM_EXTERNAL_IP>:8501
ADMIN_USERNAMES=<usernames allowed full Trip Auditor access>

POSTGRES_DB=picnix
POSTGRES_USER=picnix
POSTGRES_PASSWORD=<strong database password>
LANGGRAPH_STRICT_MSGPACK=true
AUTH_COOKIE_NAME=picnix_auth
AUTH_COOKIE_KEY=<generate with: openssl rand -hex 32>
AUTH_COOKIE_EXPIRY_DAYS=30

PHOENIX_ENABLE_AUTH=true
PHOENIX_SECRET=<generate with: openssl rand -hex 32>
PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD=<strong initial password>
PHOENIX_ENABLE_STRONG_PASSWORD_POLICY=true
PHOENIX_CSRF_TRUSTED_ORIGINS=http://<VM_EXTERNAL_IP>:6006
PHOENIX_API_KEY=
```

First start Phoenix, log in, and create a system API key:

```bash
docker compose up -d phoenix
```

Open `http://<VM_EXTERNAL_IP>:6006` and log in with:

```text
Email: admin@localhost
Password: <PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD>
```

After first login, create a Phoenix system API key from settings, write it into `.env` as `PHOENIX_API_KEY`, then start the app:

```bash
docker compose up -d --build app
```

The compose file builds `DATABASE_URL` for the app from the `POSTGRES_*` values and waits for Postgres to report healthy before starting Streamlit.

The app is available at `http://<VM_EXTERNAL_IP>:8501`. The Phoenix dashboard is available at `http://<VM_EXTERNAL_IP>:6006`.

Picnix accounts are created from the Streamlit sign-up tab. Passwords are stored as bcrypt hashes in Postgres. New accounts must verify their email through Resend before graph execution is enabled. Each account can complete 5 trip plans; after that, graph execution is blocked for new planning actions.

`PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD` is only used when the persisted Phoenix volume first creates the admin account. Later password changes happen inside Phoenix.

The current compose file sets `OBSERVABILITY_CAPTURE_CONTENT=true` for debugging visibility in Phoenix. Change that value to `"false"` in `docker-compose.yml` before handling sensitive real-user traffic.

## Tests

Run the default suite:

```bash
uv run pytest
```

Live external-service smoke tests are skipped by default. To enable them:

```bash
PICNIX_RUN_LIVE_TESTS=1 uv run pytest -m live
```
