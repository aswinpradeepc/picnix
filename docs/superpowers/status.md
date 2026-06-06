# Picnix Project Status

Last updated: 2026-06-06 (design session — N5/N6 architecture, ADRs)

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

The following contracts are fully specified in `design-context.md` and their ADRs. The next implementation session should follow this order exactly.

### N5 — Structured output validator (`graph/nodes/n5_validator.py`)

Two-pass node: Python structural checks first, then LLM semantic pass.

Python checks: timeline completeness, timeline ordering, time arithmetic, route shape, food coverage, coords validity.

LLM pass: semantic inconsistencies (implausibly short dwell time, remote morning destination with no food guidance, etc.). Returns `[{field, issue, severity: "warning"|"error"}]`.

Routing (conditional edge out of N5):
- `error` + candidates remain → remove bad destination from `validated_candidates`, reset `presented_candidate_index` to 0, set `user_confirmed = False`, increment `route_attempt_count`, route to `n4_route`. The existing `interrupt_before` fires again; user re-selects from the filtered list.
- `error` + no candidates remain → END with graceful failure message.
- `warning` only → fix in state where possible, pass `claim_failures` to N6, route to `n6_composer`.
- Clean → route to `n6_composer`.

State written: `claim_failures`; on error path also `validated_candidates`, `presented_candidate_index`, `validated_destination`, `user_confirmed`, `route_attempt_count`.

### N6 — Itinerary composer (`graph/nodes/n6_composer.py`)

Single structured LLM call that both writes prose and self-audits every factual claim. Returns `{prose, claim_audit: [{claim, source_field, verified}]}`. Claims with `verified: false` are stripped before writing `itinerary_draft`.

System prompt and output schema are specified verbatim in `design-context.md`.

State written: `itinerary_draft`.

### N7 — GeoJSON formatter (`graph/nodes/n7_formatter.py`)

Pure Python. Builds `final_geojson` FeatureCollection from `route` and `timeline`. Copies `itinerary_draft` → `final_itinerary`. Schema specified in `design-context.md`.

State written: `final_geojson`, `final_itinerary`.

### Graph wiring (`graph/graph.py`)

- Add nodes: `n5_validator`, `n6_composer`, `n7_formatter`.
- Replace `workflow.add_edge("n4_route", END)` with edges to N5.
- Add conditional edge out of N5 (routing table above).
- Add edge `n6_composer → n7_formatter → END`.
- Update Streamlit `app.py` to detect `route_attempt_count > 0` on re-interrupt and render the filtered candidate list with an explanation.

## Latest Checkpoint

- `docs/superpowers/checkpoints/2026-06-06-dynamic-food-availability.md` — N4 dynamic food availability, route-derived food search, eat-at-destination/eat-at-home/carry-or-parcel decisions, and next planning change.
