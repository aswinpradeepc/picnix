# Picnix Project Status

Last updated: 2026-06-08 (CS3 + UX fix: typed clarification inputs and combined choice/free-text answers; model upgrade to gemini-2.5-pro for N1/N4/N5)

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
- N4 route builder with round-trip Routes calls, first-class dynamic food availability decisions, LLM-driven per-destination dwell time (20 min floor, math ceiling, reason in timeline notes), and departure-time-based timeline construction. (CS2)
- N5 structured output validator with Python structural checks, Gemini semantic validation, claim failure state, and N5 error re-prompt state updates.
- N6 itinerary composer with one schema-constrained structured Gemini call, inline claim audit, and unverified-claim stripping before writing `itinerary_draft`.
- N7 GeoJSON formatter that builds `final_geojson` from route/timeline and copies `itinerary_draft` to `final_itinerary`.
- LangGraph wiring now runs `n4_route → n5_validator → n6_composer → n7_formatter → END`; N5 errors with remaining candidates route back to `n4_route` so the existing `interrupt_before` can re-prompt.
- Streamlit demo for chat, validated destination selection, N5 re-prompt messaging, N4 route/timeline/food preview, N6 final itinerary text, and N7 Mapbox/pydeck route rendering.
- `agents.md` created at project root as the shared north star for all agents working on this project. (CS0)
- Graph viz utility at `tools/graph_viz.py` exports `docs/graph.mmd` (and `docs/graph.png` if pygraphviz is installed) when `DEBUG=true`. (CS1)
- N1 now emits `clarification_prompt: {question, input_type, options, allow_custom}` alongside each assistant message; `input_type` is one of `single_select`/`multi_select`/`text`. N1 asks exactly one question per round (no chained prose). Streamlit renders checkboxes (multi-select), radio (single-select), or a text box (text) accordingly, and always offers a free-text box so the user can combine a choice with extra context — both are merged into one labeled answer. Options sourced from `INTEREST_TYPE_MAP` keys in N2. (CS3 + UX fix)
- N1, N4 (dwell time call), and N5 (semantic validation pass) upgraded to `gemini-2.5-pro` with `temperature=1.0`; N6 remains on `gemini-2.5-flash`. Requires `GOOGLE_CLOUD_LOCATION=us-central1` (Pro not available in `asia-south1`).

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

## Designed But Not Yet Implemented

N1–N7 graph nodes and Streamlit demo are complete. Remaining change sets are feature improvements and new graph nodes.

- **CS3 ✓ done (+ UX fix)** — N1 emits a typed `clarification_prompt` dict; Streamlit renders the matching control (checkbox/radio/text) and merges a selected choice with optional free-text into one answer. The earlier known issue (free-form fields returned empty `options` and hid the input) is resolved: `text` input_type now renders a dedicated text box instead of being dropped.
- **CS4** — Multi-destination selection (1–3 stops); `selected_destinations` list replaces `validated_destination`; N4 chains stops into one route.
- **CS5** — N8 plan editor: natural-language edits after itinerary is shown, routes back to N4.
- **CS6** — Google Maps deep-link export after N7.
- **CS7** — Bulleted itinerary format in N6.
- **CS8** — Region-agnostic: remove Kerala/India-specific strings from code and prompts.
- Future-scope items from `design-context.md` remain out of scope: FastAPI, auth, persistence, observability, production frontend, and multi-day planning.

## Latest Checkpoint

- `docs/superpowers/checkpoints/2026-06-06-dynamic-food-availability.md` — N4 dynamic food availability, route-derived food search, eat-at-destination/eat-at-home/carry-or-parcel decisions, and next planning change.
- `docs/superpowers/checkpoints/2026-06-06-n5-structured-validator.md` — N5 structured output validator implementation, graph wiring, tests, and remaining N6/N7/UI work.
- `docs/superpowers/checkpoints/2026-06-06-n6-n7-streamlit-demo.md` — N6/N7 implementation, full graph wiring through final output, Streamlit demo updates, and test/server verification.
- `docs/superpowers/checkpoints/2026-06-06-n6-response-schema-fix.md` — N6 live crash fix for `N6 response missing prose`, Gemini response schema enforcement, alias normalization, and regression tests.
- CS0+CS1: `agents.md` north star + graph viz utility (commit `3e08f9d`, 2026-06-08).
- CS2: LLM-driven dwell time in N4 — single Gemini call, 20 min floor, math ceiling, reason in timeline notes (commit `3f30804`, 2026-06-08).
- CS3 UX fix: typed clarification inputs (single_select/multi_select/text), one question per round, combined choice + free-text answers (commit `43047c7`, 2026-06-08).
