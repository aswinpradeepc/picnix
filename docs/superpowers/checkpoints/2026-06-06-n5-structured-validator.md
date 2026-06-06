# Checkpoint: N5 Structured Output Validator

Date: 2026-06-06

## Completed

- Added `graph/nodes/n5_validator.py`.
- N5 now validates N4 structured output before prose composition.
- Python structural checks cover timeline completeness, timeline ordering, time arithmetic, route shape, explicit meal coverage, and coordinate validity.
- N5 runs a single Gemini semantic pass after the Python checks when the structured data is usable.
- N5 writes `claim_failures` as `{field, issue, severity}` entries.
- N5 error handling removes the current destination from `validated_candidates`, resets the presented candidate cursor, clears stale route/final output fields, sets `user_confirmed = False`, and increments `route_attempt_count`.
- `graph/graph.py` now wires `n4_route → n5_validator`.
- N5 errors with remaining candidates route back to `n4_route`; the existing `interrupt_before=["n4_route"]` will pause before the next route attempt.
- The stale design-context project tree now names `n5_validator.py` and `n6_composer.py`.

## Verified

- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_graph.py tests/test_n5_validator.py -v`
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -v`
- Full default suite passed: 78 passed, 5 live tests skipped.

## Superseded Interim Behavior

- At this checkpoint, clean and warning-only N5 outcomes routed to `END` because N6 was not implemented yet.
- At this checkpoint, Streamlit still used the helper-based partial demo path and did not visibly execute N5 from the UI.
- Superseded by `2026-06-06-n6-n7-streamlit-demo.md`: N6/N7 are now implemented and the graph now continues from N5 clean/warning outcomes to N6 and N7.

## Next

- Implement `graph/nodes/n6_composer.py`.
- Implement `graph/nodes/n7_formatter.py`.
- Replace the interim N5 clean/warning `END` route with `n6_composer → n7_formatter → END`.
- Update Streamlit to handle N5 re-interrupt messaging, display `final_itinerary`, and render `final_geojson`.
