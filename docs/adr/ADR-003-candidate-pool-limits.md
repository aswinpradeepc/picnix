# ADR-003: 20 Raw Candidates / 5 Validated Queue Limits

**Status:** Accepted
**Date:** 2026-06-01

## Context

N2 fetches raw destination candidates from Google Places Nearby Search. N3 validates each candidate against opening hours, travel time, and known place issues. Each N3 validation costs 1–2 API calls (Places Details + Routes). The user-facing suggestion queue must be large enough to give real choice but small enough that validation doesn't take excessive time or API budget.

## Decision

Fix the raw candidate pool at **20** ranked results (after local dedupe) and the validated suggestion queue at **5** destinations. Places Nearby Search is called with `pageSize=20` per interest type before deduplication.

## Options Considered

- **Smaller pool (10 raw / 3 validated)**: Faster validation. Risks exhausting all candidates without filling the queue if there are many failures (e.g., weekend closures, restricted parks).
- **20 raw / 5 validated (chosen)**: Enough raw candidates to absorb a realistic rejection rate (known place issues, out-of-hours, travel-time overruns) and still fill 5 slots. Five validated suggestions gives the user genuine choice without feeling overwhelmed.
- **Larger pool (50 raw / 10 validated)**: Higher API cost per session. Validation latency increases noticeably. More than 5 suggestions is unlikely to improve user decision quality for a same-day trip.
- **Dynamic sizing**: Complex. Fixed limits are easy to reason about, test against, and adjust in one place (`graph/graph.py` `VALIDATED_SUGGESTION_LIMIT`).

## Consequences

- Worst-case N3 API calls per session: 20 Places Details + 20 Routes calls.
- The constants live in `graph/graph.py` (`VALIDATED_SUGGESTION_LIMIT = 5`) and in N2's node constants. Change both together if limits are revised.
- If fewer than 5 candidates are validated (pool exhausted), the UI shows however many were found and disables "Show me another" cleanly.
- The 20-per-search request size applies per interest type. Multiple interest types are searched and then deduped locally, so the final raw pool is still capped at 20 ranked results.
