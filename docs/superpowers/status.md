# Picnix Project Status

Last updated: 2026-06-06 (fix session — N6 response schema enforcement)

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
- N6 itinerary composer with one schema-constrained structured Gemini call, inline claim audit, and unverified-claim stripping before writing `itinerary_draft`.
- N7 GeoJSON formatter that builds `final_geojson` from route/timeline and copies `itinerary_draft` to `final_itinerary`.
- LangGraph wiring now runs `n4_route → n5_validator → n6_composer → n7_formatter → END`; N5 errors with remaining candidates route back to `n4_route` so the existing `interrupt_before` can re-prompt.
- Streamlit demo for chat, validated destination selection, N5 re-prompt messaging, N4 route/timeline/food preview, N6 final itinerary text, and N7 Mapbox/pydeck route rendering.

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

The original strict AI-layer node path is now implemented through N7. Remaining work is UI/ops polish, not new graph nodes.

- Replace the Streamlit helper-based demo flow with direct compiled LangGraph checkpoint/resume usage if stricter parity with `interrupt_before` behavior is needed.
- Improve Mapbox marker styling/layers once real demo feedback is available.
- Future-scope items from `design-context.md` remain out of scope: FastAPI, auth, persistence, observability, production frontend, and multi-day planning.

## Latest Checkpoint

- `docs/superpowers/checkpoints/2026-06-06-dynamic-food-availability.md` — N4 dynamic food availability, route-derived food search, eat-at-destination/eat-at-home/carry-or-parcel decisions, and next planning change.
- `docs/superpowers/checkpoints/2026-06-06-n5-structured-validator.md` — N5 structured output validator implementation, graph wiring, tests, and remaining N6/N7/UI work.
- `docs/superpowers/checkpoints/2026-06-06-n6-n7-streamlit-demo.md` — N6/N7 implementation, full graph wiring through final output, Streamlit demo updates, and test/server verification.
- `docs/superpowers/checkpoints/2026-06-06-n6-response-schema-fix.md` — N6 live crash fix for `N6 response missing prose`, Gemini response schema enforcement, alias normalization, and regression tests.
