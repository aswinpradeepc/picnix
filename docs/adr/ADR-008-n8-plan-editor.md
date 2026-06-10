# ADR-008: N8 Plan Editor — Park-at-Interrupt Edit Loop

**Status:** Accepted
**Date:** 2026-06-10

## Context

CS5 adds natural-language plan editing: after the final itinerary is shown, the user can type "remove the waterfall" or "leave at 7am" and the graph re-plans from N4 onward without restarting the session. A previous attempt (branch `cs5-trial-implementation`) was shelved; its design ambiguities are resolved explicitly here. Implementing CS5 also surfaced that `app.py` had never actually driven the compiled graph — it called node functions manually on a session dict — so the change set includes moving the app onto the compiled graph with real interrupts.

## Decisions

**1. Park-at-N8 interrupt model, not a conditional N7 → END edge.**
N7 → N8 is an **unconditional** edge and the graph compiles with `interrupt_before=["n4_route", "n8_editor"]`. Every completed plan parks the thread at the `n8_editor` interrupt; that pause *is* the "itinerary shown, awaiting possible edit" state. A user who is happy never resumes, and the thread stays parked — fine for a local MemorySaver app. The rejected alternative, "N7 → N8 conditional on `plan_edit_mode`", is unimplementable: on first completion `plan_edit_mode` is `False`, the run reaches END, and there is nothing left to resume into N8. The only END paths are now N5's no-stops-left path and the multiday dead end.

**2. Closed-universe edits; on-demand validation deferred (FS-3).**
N8 may only place destinations drawn from `selected_destinations` ∪ `validated_candidates` (keyed by `place_id`). Requests outside that pool are reported back as unfulfilled ("not in the validated pool for this trip"), never invented and never silently substituted. Food planning is likewise out of N8's reach: `food_stops`/`food_availability` are re-derived by N4 each re-plan, so a named food spot cannot be honored either. Both gaps are deferred as **FS-3** in `docs/future-scope.md` (on-demand validation for edit-requested places + user-pinned food stops that N4 respects).

**3. IDs-only LLM contract.**
N8's single `gemini-3.1-pro-preview` call returns place **IDs** selected from a closed set, plus optional timing changes, under an enforced `response_schema` (`response_mime_type="application/json"` **and** `response_schema`, the same enforcement as the N6 prose fix). Python (`apply_edit_result`, a pure function) maps IDs back to the real destination dicts, drops unknown IDs, falls back to the unchanged plan when the result is empty or exceeds `max_destinations` (an empty list would trigger N5's END path and kill the session), validates `HH:MM` / `0 < duration_hours ≤ 14`, resets the same route artifacts N5's replan path resets, and appends `edit_history`. The LLM never authors a destination object.

**4. App-side auto-resume rule for the N4 interrupt.**
`interrupt_before` is unconditional — it fires on *every* entry into N4, including N8 edit re-entries and N5 stop-removal replans, which would otherwise re-show the selection gallery mid-edit. `app.py` dispatches off `graph.get_state(config).next` (never off its own session flags) and auto-resumes any `n4_route` pause that carries `user_confirmed=True` (`advance_graph`, bounded by `MAX_AUTO_RESUMES`). Only an unconfirmed pause — the initial selection — renders the gallery. This subsumes both the edit pass-through (`plan_edit_mode=True` implies N8 set `user_confirmed=True`) and the CS4 auto-replan-after-removal behavior, which is unchanged. `plan_edit_mode` is reset in exactly one place: N7, when a (re-)plan completes.

## Options Considered

- **Conditional N7 → END + resume into N8** — rejected; see Decision 1.
- **Second "confirm the edit" interrupt between typing and N8** — rejected; the submission is the confirmation, and the extra pause had no UI to drive it.
- **On-demand validation for unknown places and user-named food stops** (N8 → N3 re-entry or targeted validation helpers) — deferred (FS-3); far beyond this change set's topology budget.
- **Keeping app.py's manual node-pipeline style** — rejected by the user in favor of driving the compiled graph, making the documented topology, interrupts, and this ADR true at runtime rather than simulated.

## Consequences

- `TripState` gains `plan_edit_mode`, `edit_instruction`, `edit_history` (instruction, timestamp, resulting place names, unfulfilled), and `edit_notice`.
- Every edit cycles N8 → N4 → N5 → N6 → N7 and parks at N8 again, so successive edits work for free, and a shrunk trip window flows through N5's existing stop-removal logic (`removal_notice` UI unchanged).
- On any N8 LLM failure the plan is left unchanged, `edit_notice` explains, and the graph still routes through N4 (a harmless identical rebuild) to park cleanly at N8 again.
- `app.py` now runs one graph thread per Streamlit session (`thread_id` in session state, graph cached via `st.cache_resource`); chat turns re-invoke the ENDed thread, and gallery confirms re-arm it via `update_state(..., as_node="n3_validator")` so even the graceful-failure END can resume into N4.
- The reasoning slots (N1, N4 dwell, N5 semantic, N8) moved from `gemini-2.5-pro` to `gemini-3.1-pro-preview`, which requires `GOOGLE_CLOUD_LOCATION=global`; N6 stays on `gemini-2.5-flash`.
