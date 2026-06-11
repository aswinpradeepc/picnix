# Checkpoint: N6 Response Schema Fix

Date: 2026-06-06

## Issue

The Streamlit demo crashed after confirming a destination with:

```text
graph.nodes.n6_composer.ItineraryCompositionError: N6 response missing prose.
```

## Cause

N6 configured Gemini with `response_mime_type="application/json"` but did not pass a
`response_schema`. JSON MIME mode produced valid JSON, but it did not enforce the
exact top-level `prose` key required by the parser. Live output could therefore drift
to a semantically reasonable alias such as `itinerary`, causing the parser to reject
the response.

## Fixed

- Added `COMPOSER_RESPONSE_SCHEMA` in `graph/nodes/n6_composer.py`.
- Passed the schema to `get_chat_model()` for N6 live Gemini calls.
- Kept parser compatibility for existing tests and injected fake models.
- Added normalization for likely live aliases such as `itinerary`, `itinerary_text`,
  `itinerary_draft`, `final_itinerary`, `text`, `content`, and sectioned itinerary
  objects.
- Added regression tests for alias and sectioned itinerary responses.
- Updated `docs/design-context.md` to record that N6 must use both JSON MIME mode and a
  matching response schema.

## Verified

- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_n6_composer.py -v`
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_app_helpers.py tests/test_graph.py tests/test_n6_composer.py tests/test_n7_formatter.py -v`
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -v`

Full default suite passed: 96 passed, 5 live tests skipped.

## Next

- Re-run the Streamlit owner demo with valid live API credentials.
- Watch for other model-output contracts that still rely on JSON MIME mode without a
  response schema.
