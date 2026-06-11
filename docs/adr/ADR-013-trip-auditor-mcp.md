# ADR-013: Trip Auditor — Phoenix MCP Meta-Agent with Per-User Trace Scoping

**Status:** Accepted
**Date:** 2026-06-12

## Context

Phoenix collects OpenInference traces for every graph run, but the only way to inspect them was clicking through the Phoenix dashboard. We wanted a conversational "Trip Auditor" — a Gemini agent that can answer questions like "Summarize the N3 validation failures from the last 10 trips" by reading trace data itself — without touching the trip planner graph.

Two constraints shaped the design:

1. **Isolation.** The auditor must not interfere with the `app.py` planner: no `graph/` imports, no LangGraph threads, no shared state beyond settings and the database pool.
2. **Privacy.** Phoenix system API keys grant org-wide read access, and the Compose deployment captures full trace content (`OBSERVABILITY_CAPTURE_CONTENT=true`), including user chat messages and locations. A trace-reading agent exposed to all logged-in users would leak other users' trip data.

Trace-to-user attribution is possible because the OpenInference LangChain instrumentor promotes the LangGraph `thread_id` run-metadata key to the `session.id` span attribute (verified empirically against the installed versions), and the Picnix `trip_runs` table maps `username → thread_id`.

## Decision

Add `pages/1_Trip_Auditor.py`, a standalone Streamlit page running a `gemini-3.1-pro-preview` tool-calling loop (via the central `get_chat_model()` wrapper) with two access modes decided server-side after login:

- **Admin mode** (`ADMIN_USERNAMES` allowlist in `.env`, deny-by-default when empty): the agent gets the full Arize Phoenix MCP toolset. The MCP server is the Node-based `@arizeai/phoenix-mcp`, launched over stdio via `npx` with `--baseUrl $PHOENIX_BASE_URL` and `--apiKey $PHOENIX_API_KEY`, connected through `langchain-mcp-adapters`. The Docker image installs Node.js 22 and pre-installs the package so runtime `npx` resolves offline.
- **User mode** (any other logged-in account): the agent gets exactly two Python tools. `list_my_trips` reads the logged-in user's thread ids from `trip_runs` (`list_user_trip_threads()` in `persistence/database.py`); `get_trip_spans(thread_id)` re-validates ownership against the database on every call, then fetches spans from Phoenix's REST API (`GET /v1/projects/{project}/spans?attribute=session.id:<thread_id>`). The privacy boundary is the tool surface, not the prompt: the model has no tool that can reach another user's traces, so prompt injection cannot widen the scope.

`PHOENIX_BASE_URL` (Phoenix HTTP endpoint, `http://phoenix:6006` in Compose) and `ADMIN_USERNAMES` are read through `config/settings.py`.

## Options Considered

- **Full MCP toolset for everyone, restricted by prompt instructions:** Rejected. Prompt-level restrictions are not a security boundary; a system API key behind them exposes all users' trace content.
- **MCP tool interceptors to filter non-admin calls:** Rejected. Enforcing per-user filters would require knowing every MCP tool's parameter semantics and output shape; brittle across `@arizeai/phoenix-mcp` releases.
- **`arize-phoenix-client` Python SDK for the scoped path:** Rejected. The two REST calls needed are trivial with `requests` (already a dependency); a new SDK dependency wasn't justified.
- **Admin-only feature, no user mode:** Superseded. Per-user scoping is enforceable cheaply because spans already carry `session.id = thread_id`, so users get self-service trace auditing.

## Consequences

- The app image now ships Node.js 22 (NodeSource) solely for the MCP server; image size grows accordingly.
- Admin mode depends on `@arizeai/phoenix-mcp` tracking the Phoenix server's API; the package is pre-installed at build time, so upgrades happen via image rebuilds.
- User-mode scoping relies on the instrumentor's `thread_id → session.id` metadata mapping. If the OpenInference or LangGraph versions change that behavior, scoped queries return nothing (fail-closed) — a regression test or smoke check should accompany those upgrades.
- The auditor reuses the planner's trial-gated accounts but does not count against trip limits; it is read-only over Phoenix and Postgres.
- With `OBSERVABILITY_CAPTURE_CONTENT=true`, admins can read raw user content through the auditor. Operators should flip it to `false` before handling sensitive real-user traffic (already documented in the README).
