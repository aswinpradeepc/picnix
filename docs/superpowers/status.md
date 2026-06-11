# Picnix Project Status

Last updated: 2026-06-11 (BACKEND-PERSIST-1: ADR-010 accepted for PostgreSQL, streamlit-authenticator, and LangGraph Postgres checkpointing)

## Source Of Truth

- `design-context.md` is the project Bible. Product behavior, graph contracts, API choices, and fixed planning limits should be reflected there first.
- `pyproject.toml` is the dependency source of truth. Dependencies are added with `uv add <package>`, and `uv.lock` is committed.

## Planning Docs

- `docs/superpowers/plans/2026-05-31-bootstrap.md` — project scaffold, uv setup, `TripState`, settings.
- `docs/superpowers/plans/2026-05-31-tool-layer.md` — Google Maps, Mapbox, and Gemini/Vertex tool wrappers.
- `docs/superpowers/plans/2026-06-01-validated-suggestion-queue.md` — fixed raw candidate pool and validated suggestion queue.

## Design Specs

- `docs/superpowers/specs/2026-06-01-validated-suggestion-queue-design.md` — approved design for showing only N3-validated suggestions to users.

## Current Implemented Slice

- N1 intent collection with Gemini through `ChatGoogleGenerativeAI` using Vertex AI ADC.
- N2 short-trip candidate discovery with Google Geocoding and Places Nearby Search.
- N3 destination validation with Places Details, opening-hours checks, markdown-backed known issue checks, and Routes travel-time checks.
- N4 route builder that chains `selected_destinations` (1–3 stops) into a single round trip via one Routes `computeRoutes` call with intermediate waypoints, builds one unified timeline across all stops, makes per-segment food decisions, and runs one batched LLM dwell-time call for all stops (20 min floor, math ceiling, reason in timeline notes). (CS2, CS4)
- N5 structured output validator with Python structural checks (generalised to N stops), Gemini semantic validation, and claim failure state. On error it drops the unplannable stop from `selected_destinations` (with a user-facing `removal_notice`) and re-routes the remaining stops; routes to END only when none remain. (CS4)
- N6 itinerary composer with one schema-constrained structured Gemini call, inline claim audit, and unverified-claim stripping before writing `itinerary_draft`.
- N7 GeoJSON formatter that builds `final_geojson` from route/timeline (one Point per stop labelled "Stop N", full multi-stop LineString, leave-stop pins skipped) and copies `itinerary_draft` to `final_itinerary`. (CS4)
- N8 plan editor: after the plan is shown the graph parks at `interrupt_before=["n8_editor"]`; a natural-language edit resumes N8 → N4 → N5 → N6 → N7 and parks again. One `gemini-3.1-pro-preview` call returns place IDs from the closed validated pool under an enforced `response_schema`; pure-Python `apply_edit_result` maps IDs to real dicts, validates timing changes, and never writes an empty stop list. (CS5, ADR-008)
- LangGraph wiring now runs `n4_route → n5_validator → n6_composer → n7_formatter → n8_editor → n4_route` (N7→N8 unconditional; END only from N5's no-stops path and the multiday dead end); N5 errors with surviving stops route back to `n4_route` to re-plan.
- `app.py` drives the compiled graph: one MemorySaver thread per Streamlit session, panel dispatch off `graph.get_state(config).next`, and `advance_graph` auto-resumes every confirmed `n4_route` pause (edit re-entries and N5 replans) so the gallery only renders for the initial selection. (CS5)
- Streamlit demo for chat, a scrollable multi-select destination card gallery (checkbox per card, "Confirm selection" + "Load more options"), N5 stop-removal messaging, N4 route/timeline/food preview, N6 final itinerary text, and N7 Mapbox/pydeck route rendering. (CS4)
- `agents.md` created at project root as the shared north star for all agents working on this project. (CS0)
- Graph viz utility at `tools/graph_viz.py` exports `docs/graph.mmd` (and `docs/graph.png` if pygraphviz is installed) when `DEBUG=true`. (CS1)
- N1 now emits `clarification_prompt: {question, input_type, options, allow_custom}` alongside each assistant message; `input_type` is one of `single_select`/`multi_select`/`text`. N1 asks exactly one question per round (no chained prose). Streamlit renders checkboxes (multi-select), radio (single-select), or a text box (text) accordingly, and always offers a free-text box so the user can combine a choice with extra context — both are merged into one labeled answer. Options sourced from `INTEREST_TYPE_MAP` keys in N2. (CS3 + UX fix)
- Reasoning slots — N1, N4 (dwell time call), N5 (semantic validation pass), and N8 (plan editor) — run `gemini-3.1-pro-preview` (`REASONING_GEMINI_MODEL`) with `temperature=1.0`; N6 remains on `gemini-2.5-flash`. Requires `GOOGLE_CLOUD_LOCATION=global` (3.1 Pro is global-endpoint only; 3 Pro preview was discontinued 2026-03).
- Google Maps deep-link export: `tools/gmaps.py` `generate_gmaps_link(timeline)` builds a round-trip URL (origin=start, destination=start, waypoints=all destination stops); rendered as `st.link_button("Open in Google Maps 🗺️")` after the final itinerary. (CS6)
- N6 itinerary format updated to hybrid: one bold section header per stop + one punchy vibe sentence + 1–2 bullet points for must-know facts. (CS7)
- Region-agnostic: N6 system prompt removes "Kerala local" identity and Malayalam warmth phrases; replaced with a locally neutral tone instruction. `docs/known-place-issues.md` cleared of Kerala-specific entries and given a region-agnostic header. `README.md` updated to remove Kerala reference. (CS8)
- Phoenix-first observability bootstrap: `observability/bootstrap.py` calls `phoenix.otel.register(...)` and the OpenInference `LangChainInstrumentor` before graph imports in `app.py`. Controlled by `OBSERVABILITY_ENABLED=false`, `ARIZE_PRODUCT=phoenix`, and `OBSERVABILITY_CAPTURE_CONTENT=false` by default for local runs. The local Phoenix server is available through the optional `phoenix` extra. The deployment path is now a single GCP Compute Engine VM running Docker Compose with exactly two services: `app` and `phoenix`; the app sends traces to `http://phoenix:6006/v1/traces`. Phoenix dashboard auth is enabled via `.env` and the app uses `PHOENIX_API_KEY` after a Phoenix system key is created. Manual node/tool spans and Arize AX are deferred. (OBS-1, DEPLOY-OBS, ADR-009)
- Docker deployment artifacts: root `Dockerfile` builds the Streamlit app with `uv`; root `docker-compose.yml` runs `arizephoenix/phoenix:latest` plus the Picnix app, exposes ports 6006/4317/8501, persists Phoenix data in `phoenix-data`, and mounts local ADC credentials into the app container.

## Current Fixed Limits

- Raw candidate pool: 20 ranked Places candidates.
- Validated suggestion queue: 5 destinations.
- Nearby Search request size: 20 results per interest search before local dedupe/ranking.
- Departure time is collected as `constraints["departure_time"]`; N3/N4 must not hardcode a fixed trip start time.
- Known place restrictions and recurring issues live in `docs/known-place-issues.md`, not in node prompts or Python place-name lists.
- Food planning is route/destination-derived. N4 must not use static route towns, hubs, cities, or checkpoints for meal recommendations.

## Architecture Decision Records

- `docs/adr/` — formal ADRs for all significant architectural decisions. Read before implementing new nodes or changing the graph shape.
- ADR-001 through ADR-005: retroactive records for LangGraph, Vertex AI, candidate limits, interrupt placement, and dynamic food search.
- ADR-006: N5/N6 swap — validate structured N4 output before composing prose. Includes N5→N4 re-prompt loop design.
- ADR-007: Multi-destination routing & stop selection (CS4) — single `computeRoutes` call with intermediate waypoints; current visit order = candidate-list order (no optimization); current removal = N5 auto-drops the last stop. Deferred revisits documented in `docs/future-scope.md` (FS-1 stop order, FS-2 user-driven removal).
- ADR-008: N8 plan editor (CS5) — park-at-N8 interrupt model vs. conditional N7→END, closed-universe edits with FS-3 deferral, IDs-only LLM contract, app-side auto-resume rule for the N4 interrupt.
- ADR-009: Phoenix-first observability — Phoenix is the active milestone target via OpenInference LangChain auto-instrumentation; deployment is self-hosted Phoenix + app on one Compute Engine VM via Docker Compose; Arize AX and manual spans are deferred.
- ADR-010: Backend authentication and production persistence — PostgreSQL 15 becomes the app persistence layer, `streamlit-authenticator` handles Streamlit registration/login, and LangGraph checkpointing moves from `MemorySaver` to a PostgreSQL-backed checkpointer.

## Deferred Discussions (Future Scope)

- `docs/future-scope.md` — agreed-to-revisit design discussions that are intentionally **not** scheduled into a change set yet.
- **FS-1** — Visit order of selected stops (geo-optimize vs. user-controlled vs. current candidate-list order).
- **FS-2** — User-driven stop removal: when a plan does not fit, show the stops with distance / travel time / time-spent and let the user choose what to remove (replaces the current auto-drop-last behavior).
- **FS-3** — Edit-time additions: validate edit-requested places on demand (so "add Kadamakudy lake view point" works when it isn't in the validated pool, and the place joins `validated_candidates`) and let food edits pin a user-named food stop ("dinner at Pathirakozhi, Kalamassery") that N4 respects on re-plans.
- **FS-7** — Arize AX production observability, dashboards, and product monitoring workflow after backend/user/deployment shape is clearer.

## Designed But Not Yet Implemented

N1–N7 graph nodes and Streamlit demo are complete. Remaining change sets are feature improvements and new graph nodes.

- **CS3 ✓ done (+ UX fix)** — N1 emits a typed `clarification_prompt` dict; Streamlit renders the matching control (checkbox/radio/text) and merges a selected choice with optional free-text into one answer. The earlier known issue (free-form fields returned empty `options` and hid the input) is resolved: `text` input_type now renders a dedicated text box instead of being dropped.
- **CS4 ✓ done** — Multi-destination selection (1–3 stops). `selected_destinations` (+ `max_destinations`, `presented_candidate_indices`, `removal_notice`) replaces `validated_destination`/`presented_candidate_index`. `gmaps.compute_route` gained `intermediates` → one `computeRoutes` call with waypoints + per-leg `normalized_legs`. N4 chains stops into one route/timeline with per-segment food; N5 drops the unplannable stop and re-plans the rest; N7 labels "Stop N". Streamlit shows a scrollable multi-select card gallery.
- **CS5 ✓ done** — N8 plan editor (cs5.md v2 spec): park-at-N8 interrupt, closed-universe IDs-only edits, app-side auto-resume of the N4 interrupt; FS-3 (edit-time place additions + user-directed food stops) deferred. Recorded in ADR-008.
- **CS6 ✓ done** — Google Maps deep-link export after N7.
- **CS7 ✓ done** — Hybrid itinerary format in N6 (bold header + vibe sentence + bullets).
- **CS8 ✓ done** — Region-agnostic: Kerala/India-specific strings removed from code, prompts, and docs.

All next_milestone.md change sets (CS0–CS8) are complete. The AI layer MVP is shipped.

## Active Next Milestone

Backend, user management, and production persistence are now promoted into active scope under ADR-010:

- Docker Compose will move from `app + phoenix` to `app + phoenix + db`, where `db` is PostgreSQL 15 with a persistent `postgres-data` volume.
- App configuration will read `DATABASE_URL`.
- Streamlit will add authenticated registration/login through `streamlit-authenticator`.
- PostgreSQL will store user accounts, password hashes, trial counters, and LangGraph checkpoint state.
- Trial enforcement will block graph execution once `users.trips_planned >= 5` and will increment only after N7 successfully completes for a graph thread.

Future-scope items from `design-context.md` remain out of scope unless explicitly promoted: FastAPI, production frontend, multi-day planning, Arize AX, and manual observability spans. Auth and persistence are now promoted into active scope by ADR-010.

## Latest Checkpoint

- `docs/superpowers/checkpoints/2026-06-06-dynamic-food-availability.md` — N4 dynamic food availability, route-derived food search, eat-at-destination/eat-at-home/carry-or-parcel decisions, and next planning change.
- `docs/superpowers/checkpoints/2026-06-06-n5-structured-validator.md` — N5 structured output validator implementation, graph wiring, tests, and remaining N6/N7/UI work.
- `docs/superpowers/checkpoints/2026-06-06-n6-n7-streamlit-demo.md` — N6/N7 implementation, full graph wiring through final output, Streamlit demo updates, and test/server verification.
- `docs/superpowers/checkpoints/2026-06-06-n6-response-schema-fix.md` — N6 live crash fix for `N6 response missing prose`, Gemini response schema enforcement, alias normalization, and regression tests.
- CS0+CS1: `agents.md` north star + graph viz utility (commit `3e08f9d`, 2026-06-08).
- CS2: LLM-driven dwell time in N4 — single Gemini call, 20 min floor, math ceiling, reason in timeline notes (commit `3f30804`, 2026-06-08).
- CS3 UX fix: typed clarification inputs (single_select/multi_select/text), one question per round, combined choice + free-text answers (commit `43047c7`, 2026-06-08).
- CS4: multi-destination selection (1–3 stops) — single waypoint Routes call, per-segment food, N5 stop-removal/re-plan, scrollable multi-select card gallery (2026-06-08; commit `bcb9db8`).
- CS5: N8 plan editor — park-at-N8 interrupt, closed-universe IDs-only edits, graph-driven app.py, gemini-3.1-pro-preview reasoning slots (2026-06-10).
- CS6: Google Maps deep-link export — `generate_gmaps_link` in gmaps.py, `st.link_button` in app.py (2026-06-10).
- CS7: Hybrid itinerary format — bold header + vibe sentence + bullets per stop in N6 (2026-06-10).
- CS8: Region-agnostic — N6 prompt neutralised, known-place-issues.md cleared of Kerala entries, README generalised (2026-06-10). All CS0–CS8 complete.
