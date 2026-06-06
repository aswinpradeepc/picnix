# ADR-004: Human Interrupt Placed Before N4 (Not N3)

**Status:** Accepted
**Date:** 2026-06-01

## Context

The user must confirm a destination before the graph does expensive work (Routes API round-trip call, food search, timeline construction). The question is where in the graph to pause for user confirmation: immediately after each N3 validation, or once the full validated queue is built.

## Decision

Place `interrupt_before=["n4_route"]`. N3 runs to completion (building the full 5-item validated queue) before the graph pauses. The interrupt fires once, the user browses `validated_candidates` via "Show me another", then confirms. N4 only runs after `user_confirmed = True`.

## Options Considered

- **Interrupt after each N3 validation (interrupt_before=["n3_validator"])**: User sees candidates as they are validated. Feels more responsive. But: the interrupt fires up to 20 times; resuming the graph 20 times per session adds complexity to the Streamlit state machine. Also, the user may accept a candidate before better ones have been found.
- **Interrupt before N4 (chosen)**: Single pause point. N3 runs fully, producing the best available queue. User browses a pre-built queue with no further API calls mid-selection. Streamlit only needs to handle one resume event per trip. "Show me another" is a pure state-dict operation — no graph resume needed; only `presented_candidate_index` advances within the already-built queue.
- **No interrupt (fully automatic)**: First validated candidate is used without asking. Removes user agency; not appropriate for a personal trip planner.

## Consequences

- "Show me another" does not trigger a graph resume — it is handled in `graph/graph.py`'s `request_next_candidate()` helper, which advances `presented_candidate_index` within the existing `validated_candidates` list.
- If the user wants a destination outside the 5-slot queue, there is no mechanism to fetch more candidates without restarting the session. This is acceptable for the current scope.
- N4 is guaranteed to run only once per confirmed destination. There is no partial-route state to clean up if the user changes their mind (they can only change their mind before N4, not during it).
