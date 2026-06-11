# agents.md — Picnix Project North Star

This file is the shared reference for every agent (Claude Code, Codex, Antigravity, or any future agent) working on this project. Read it before touching any code. Keep it up to date as scope, stack, or file ownership changes.

---

## Project Identity

- **Name:** Picnix
- **Purpose:** Conversational AI trip planner. Takes user constraints via chat, builds a time-accurate itinerary, renders it on a Mapbox map.
- **Status:** Active development. Moving from local MVP to authenticated, persistent Docker Compose deployment. No billing or production web frontend yet.

---

## Tech Stack

| Concern | Tool |
|---|---|
| AI graph | LangGraph (Python) |
| LLM | Google Vertex AI via `langchain-google-genai` (`ChatGoogleGenerativeAI`) — `gemini-3.1-pro-preview` for reasoning slots (N1, N4 dwell, N5 semantic, N8), `gemini-2.5-flash` for N6 prose. Requires `GOOGLE_CLOUD_LOCATION=global` |
| Map rendering | Mapbox GL JS, via `pydeck` in Streamlit |
| Place search & data | Google Maps Places API (New) |
| Routing & distance | Google Maps Routes API |
| POI access validation | Google Maps Places API — check opening hours, access details |
| UI framework | Streamlit |
| Config | `python-dotenv`, `.env` file for all keys |
| Package management | `uv`, with `pyproject.toml` and `uv.lock` |
| Observability | Phoenix via OpenInference LangChain auto-instrumentation. Disabled by default for local runs; the Docker Compose deployment enables it and sends traces to the self-hosted Phoenix container. Local Phoenix server is optional via `uv run --extra phoenix phoenix serve`. |
| Persistence | PostgreSQL 15 via Docker Compose `db` service; app config reads `DATABASE_URL` |
| Graph checkpointing | LangGraph PostgreSQL checkpointer (`PostgresSaver` or connection-pool-backed equivalent) |
| Authentication | `streamlit-authenticator` in the Streamlit frontend, backed by the PostgreSQL `users` table |

**No other external planning/geo services.** No Overpass, no ORS, no OSRM, no OpenStreetMap API calls. Google Maps handles all geo data. Mapbox handles all rendering. Phoenix is allowed only for observability under ADR-009.

### Environment Variables

```
GOOGLE_MAPS_API_KEY=
MAPBOX_TOKEN=
GOOGLE_CLOUD_PROJECT=        # your GCP project ID
GOOGLE_CLOUD_LOCATION=       # Vertex AI region, e.g. us-central1
GOOGLE_APPLICATION_CREDENTIALS=  # optional; leave blank/unset for local ADC OAuth
OBSERVABILITY_ENABLED=false  # optional Phoenix tracing
ARIZE_PRODUCT=phoenix
ARIZE_PROJECT_NAME=picnix-local
OBSERVABILITY_CAPTURE_CONTENT=false
PHOENIX_API_KEY=             # Phoenix system API key when self-hosted auth is enabled
PHOENIX_COLLECTOR_ENDPOINT=  # optional; local Phoenix OTLP collector defaults to localhost:4317
DATABASE_URL=                # optional; defaults to local Postgres fallback in config/settings.py
```

### Required Google Cloud APIs

| API | Service name | Used by | Purpose |
|---|---|---|---|
| Places API (New) | `places.googleapis.com` | `tools/gmaps.py`, N2, N3, N4 | Destination search, place details, opening hours/access validation, food stop search |
| Geocoding API | `geocoding-backend.googleapis.com` | `tools/gmaps.py`, N2 | Convert user start-location text into latitude/longitude |
| Routes API | `routes.googleapis.com` | `tools/gmaps.py`, N3, N4 | Actual travel-time validation, round-trip route geometry, legs, ETAs |
| Vertex AI API | `aiplatform.googleapis.com` | `tools/vertex.py`, N1, N4, N5, N6, N8 | Gemini calls (3.1 Pro preview + 2.5 Flash) through `ChatGoogleGenerativeAI` using the Vertex AI backend |

### Package Management

Use `uv` for dependency management. `pyproject.toml` is the single source of truth for dependencies. Add dependencies with `uv add <package>`, commit `uv.lock`, and run the app with `uv run streamlit run app.py`. Do not create or use `requirements.txt`.

---

## What Is In Scope Right Now

- LangGraph AI graph (7 nodes N1–N7 + N8 plan editor)
- Streamlit UI
- Google Maps API integrations (Places, Geocoding, Routes)
- Mapbox rendering via pydeck
- Phoenix observability through global OpenInference LangChain instrumentation
- Docker Compose deployment: Picnix app + self-hosted Phoenix + PostgreSQL
- Streamlit authentication, persisted user accounts, and a strict 5 completed-trip trial limit per account
- PostgreSQL-backed LangGraph checkpoint persistence

---

## What Is Explicitly Out of Scope — Do Not Build These

- LangSmith observability tooling
- Arize AX production observability
- Manual node/tool span instrumentation
- Production web frontend
- Docker / cloud deployment beyond the current Compose stack
- Token usage tracking

---

## File Ownership Map

```
app.py                      — Streamlit UI. Drives the compiled graph: one thread per session, dispatches panels off graph.get_state(config).next.
graph/state.py              — TripState schema. Change only when a node needs new fields.
graph/graph.py              — Node wiring, edges, interrupt config. Change when graph topology changes.
graph/nodes/                — One file per node. Each node owns its section of state.
tools/gmaps.py              — All Google Maps HTTP calls. No business logic here.
tools/mapbox.py             — Mapbox token helpers only.
config/settings.py          — All env var loading. No hardcoded strings elsewhere.
db/ or persistence module    — PostgreSQL connection pooling, schema setup, user/trial helpers, LangGraph checkpointer factory.
observability/bootstrap.py   — Phoenix/OpenInference setup. Called before graph imports; no manual spans in current scope.
docs/known-place-issues.md  — Durable place-level exceptions. Update here, not in node code.
agents.md                   — This file. Update when scope, stack, or ownership changes.
```

---

## Current Graph Topology / Architecture Flow

Runtime containers:

```
Browser → Streamlit app → LangGraph N1-N8
                     ↘ PostgreSQL db (users, trial counters, LangGraph checkpoints)
                     ↘ Phoenix (OpenInference traces)
```

```
N1 (intent) → conditional edge → N2 (isochrone) → N3 (validator) →
[human interrupt] → N4 (route) → N5 (structured validator) →
N6 (composer) → N7 (formatter) → [human interrupt: plan editor] → N8 (plan editor) → N4
```

Node responsibilities at a glance:

| Node | Type | Responsibility |
|---|---|---|
| N1 | Conversational LLM | Collect trip constraints via chat |
| N2 | Tool-calling | Geocode start location, fetch raw candidate pool (up to 20 places) |
| N3 | Tool-calling + retry | Validate raw candidates — hours, travel time, known issues — build queue of up to 5 |
| N4 | Tool-calling | Build round-trip route, food availability, timeline |
| N5 | Python + LLM | Validate N4 structured output; route back to N4 on error |
| N6 | LLM structured output | Compose prose itinerary with inline claim audit |
| N7 | Pure Python | Build final GeoJSON FeatureCollection for Mapbox; copy itinerary to final output |
| N8 | LLM | Accept natural-language plan edits, update destination list, route back to N4 |

---

## Coding Standards

- All node functions must have type hints and a one-paragraph docstring explaining what they read from state and what they write to state.
- All Google Maps API calls must be wrapped in try/except with explicit error messages — never let an API failure crash the graph silently.
- No hardcoded strings outside of `config/settings.py` and the interest→type map in N2.
- The LangGraph graph must be compiled with a PostgreSQL-backed checkpointer in production so human interrupts and N8 parked threads survive restarts.
- Use `python-dotenv` and never reference `os.environ` directly — always go through `config/settings.py`.

---

## Change Log

| Date | Change Set | Summary |
|------|------------|---------|
| 2026-06-08 | CS0 | Created agents.md as shared north star for all agents working on this project |
| 2026-06-08 | CS1 | Graph viz utility: tools/graph_viz.py exports docs/graph.mmd (and docs/graph.png if pygraphviz installed) when DEBUG=true |
| 2026-06-08 | CS2 | LLM-driven dwell time in N4: single Gemini call determines dwell_minutes with 20 min floor and math ceiling; reason written to timeline notes; static lookup removed |
| 2026-06-08 | CS2 | LLM-driven dwell time in N4: single Gemini call per run determines dwell_minutes with 20 min floor and math ceiling; reason written to timeline notes; static lookup kept as silent fallback |
| 2026-06-08 | CS3 | N1 emits clarification_prompt dict when asking questions; Streamlit renders radio buttons + free-text fallback; options sourced from INTEREST_TYPE_MAP keys in N2 |
| 2026-06-08 | model | N1, N4 dwell time, N5 semantic pass upgraded to gemini-2.5-pro (temperature=1.0); N6 stays on gemini-2.5-flash; REASONING_GEMINI_MODEL constant in tools/vertex.py; requires us-central1 |
| 2026-06-08 | CS3 fix | clarification_prompt gains input_type (single_select/multi_select/text); N1 asks one question per round; Streamlit renders checkboxes (multi) / radio (single) / text box accordingly and merges selection + free-text into one labeled answer |
| 2026-06-08 | CS4 | Multi-destination selection (1-3 stops). State: selected_destinations/max_destinations/presented_candidate_indices/removal_notice replace validated_destination/presented_candidate_index. gmaps.compute_route gains intermediates → single computeRoutes call with waypoints + per-leg normalized_legs. N4 chains start→stops→start, one timeline, per-segment food, batched dwell-time call. N5 drops the unplannable stop and re-routes the rest (END when none remain). N7 labels Stop N and skips leave-stop pins. Streamlit shows a scrollable card gallery with per-card checkboxes, Confirm selection + Load more options |
| 2026-06-10 | model | Reasoning slots (N1, N4 dwell, N5 semantic, N8) upgraded gemini-2.5-pro → gemini-3.1-pro-preview; requires GOOGLE_CLOUD_LOCATION=global; N6 stays on gemini-2.5-flash. N4 dwell parser handles list-content responses |
| 2026-06-10 | CS5 | N8 plan editor (ADR-008). State: plan_edit_mode/edit_instruction/edit_history/edit_notice. N7→N8 unconditional, N8→N4, interrupt_before adds n8_editor — every finished plan parks at N8. N8 = one LLM call returning place IDs from the closed validated pool under enforced response_schema + pure-Python enforcement (apply_edit_result). N7 resets plan_edit_mode. app.py refactored to drive the compiled graph: per-session thread, get_state(.next) dispatch, auto-resume of confirmed n4_route pauses (advance_graph) |
| 2026-06-10 | CS6 | Google Maps export link. tools/gmaps.py gains generate_gmaps_link(timeline) — pure round-trip URL: origin=start, destination=start, waypoints=all destination stops. app.py render_plan shows st.link_button("Open in Google Maps 🗺️") after final itinerary. |
| 2026-06-10 | CS7 | Hybrid itinerary format. N6 system prompt: bold section header + one warm prose sentence (vibe) + 2–3 bullet points (key facts/tips) per stop. prose schema description updated to match. |
| 2026-06-10 | CS8 | Region-agnostic. N6 system prompt: removed "Kerala local" identity and Malayalam warmth phrases; replaced with locally neutral tone instruction. known-place-issues.md: removed Kerala-specific rows (Anamudi Peak, Eravikulam NP), added region-agnostic header. README: removed Kerala reference, generalised GOOGLE_CLOUD_LOCATION example. |
| 2026-06-11 | OBS-1 | Phoenix-first observability. Added ADR-009, Phoenix/OpenInference env vars, global LangChain/LangGraph auto-instrumentation bootstrap, optional local Phoenix server extra, and deferred Arize AX/manual spans to future scope. |
| 2026-06-11 | DEPLOY-OBS | Docker Compose observability deployment: app + self-hosted Phoenix on one GCP Compute Engine VM, Phoenix auth env wiring, app traces routed to `http://phoenix:6006/v1/traces`. |
| 2026-06-11 | BACKEND-PERSIST-1 | Phase 1 docs for backend/auth/persistence milestone. Added ADR-010, moved auth/database out of hard out-of-scope, and documented PostgreSQL + streamlit-authenticator + LangGraph Postgres checkpointing direction. |
| 2026-06-11 | BACKEND-PERSIST-2 | Phase 2 dependency and infrastructure setup. Added streamlit-authenticator, psycopg/psycopg-pool, langgraph-checkpoint-postgres, DATABASE_URL config, and a health-checked PostgreSQL db service with postgres-data volume. |
