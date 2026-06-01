# Validated Suggestion Queue Design

## Goal

Make Picnix show only usable, validated destinations to the user. Raw Google Places candidates that fail hours, access, or travel-time checks must stay internal and must not appear as the next suggestion.

## Fixed Limits

- Raw candidate pool: `20` ranked candidates after dedupe.
- User-facing validated suggestion queue: `5` destinations.
- Google Places Nearby Search request size: `20` results per interest search, then local dedupe and ranking trims the pool to `20`.

## Data Model

`candidates` remains the raw ranked pool. `candidate_index` becomes the raw validation cursor.

Add `validated_candidates` as the queue of destinations that passed N3. Add `presented_candidate_index` as the UI cursor inside that validated queue. `validated_destination` remains as the current destination shown by the Streamlit partial demo.

`validation_failures` remains useful for diagnostics and tests, but it is not the primary user-facing suggestion surface.

## Flow

N2 fetches and ranks up to `20` raw candidates. N3 validates candidates from `candidate_index` until either `5` valid destinations are collected or the raw pool is exhausted. The first validated destination is shown.

When the user clicks "Show me another", Picnix advances `presented_candidate_index` within `validated_candidates`. It does not expose validation failures as suggestions. If no validated suggestions remain, the UI shows a clean no-more-options message.

## Testing

Tests should cover the fixed raw-pool limit, validated queue construction, rejection advancing within the validated queue, and the UI helper behavior for no remaining validated options.
