# Checkpoint: N6/N7 And Streamlit Demo

Date: 2026-06-06

## Completed

- Added `graph/nodes/n6_composer.py`.
- N6 uses one structured Gemini call to write prose and return `claim_audit`.
- N6 removes sentence-like prose segments containing unverified claim audit entries before writing `itinerary_draft`.
- Added `graph/nodes/n7_formatter.py`.
- N7 builds `final_geojson` as a FeatureCollection with route LineString and timeline waypoint Point features.
- N7 copies `itinerary_draft` to `final_itinerary`.
- `graph/graph.py` now wires `n4_route → n5_validator → n6_composer → n7_formatter → END`.
- N5 error routing still returns to `n4_route` with the filtered candidate list when candidates remain.
- Streamlit now runs the confirmed-destination helper pipeline through N7.
- Streamlit displays N5 re-prompt messaging when `route_attempt_count > 0`.
- Streamlit displays `final_itinerary` and renders `final_geojson` through pydeck/Mapbox when `MAPBOX_TOKEN` is configured.

## Verified

- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_app_helpers.py tests/test_graph.py tests/test_n6_composer.py tests/test_n7_formatter.py -v`
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -v`
- Full default suite passed: 94 passed, 5 live tests skipped.
- Streamlit server started on port `8501`.
- Local HTTP smoke check returned `HTTP/1.1 200 OK`.

## Current Notes

- The Streamlit UI still uses helper functions to run the demo flow instead of invoking the compiled LangGraph with checkpoint/resume.
- This is acceptable for the current demo but should be revisited if the UI must exactly mirror LangGraph `interrupt_before` semantics.
- A real live demo requires valid `.env` values, Google Maps APIs, Vertex AI ADC, and optionally `MAPBOX_TOKEN` for map rendering.

## Next

- Update status/docs and commit this milestone.
- Run a live owner demo with configured API credentials.
- Collect UI feedback before polishing Mapbox layers or switching Streamlit to direct graph checkpoint/resume calls.
