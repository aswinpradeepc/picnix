# Picnix Project Status

Last updated: 2026-06-06 (implementation session — N5 structured validator)

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
- N4 route builder with round-trip Routes calls, first-class dynamic food availability decisions, destination dwell-time caps, and departure-time-based timeline construction.
- N5 structured output validator with Python structural checks, Gemini semantic validation, claim failure state, and N5 error re-prompt state updates.
- LangGraph wiring now runs `n4_route → n5_validator`; N5 errors with remaining candidates route back to `n4_route` so the existing `interrupt_before` can re-prompt.
- Streamlit partial demo for chat, current validated destination, accept, next validated suggestion, locked chosen destination, N4 route preview, and food availability decisions.

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

The following contracts are fully specified in `design-context.md` and their ADRs. The next implementation session should continue from N6.

### N6 — Itinerary composer (`graph/nodes/n6_composer.py`)

Single structured LLM call that both writes prose and self-audits every factual claim. Returns `{prose, claim_audit: [{claim, source_field, verified}]}`. Claims with `verified: false` are stripped before writing `itinerary_draft`.

System prompt and output schema are specified verbatim in `design-context.md`.

State written: `itinerary_draft`.

### N7 — GeoJSON formatter (`graph/nodes/n7_formatter.py`)

Pure Python. Builds `final_geojson` FeatureCollection from `route` and `timeline`. Copies `itinerary_draft` → `final_itinerary`. Schema specified in `design-context.md`.

State written: `final_geojson`, `final_itinerary`.

### Graph wiring (`graph/graph.py`)

- Add nodes: `n6_composer`, `n7_formatter`.
- Replace the current interim N5 clean/warning `END` path with `n6_composer`.
- Add edge `n6_composer → n7_formatter → END`.
- Update Streamlit `app.py` to detect `route_attempt_count > 0` on re-interrupt and render the filtered candidate list with an explanation.

## Latest Checkpoint

- `docs/superpowers/checkpoints/2026-06-06-dynamic-food-availability.md` — N4 dynamic food availability, route-derived food search, eat-at-destination/eat-at-home/carry-or-parcel decisions, and next planning change.
- `docs/superpowers/checkpoints/2026-06-06-n5-structured-validator.md` — N5 structured output validator implementation, graph wiring, tests, and remaining N6/N7/UI work.
