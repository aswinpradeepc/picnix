# Picnix — Future Scope Discussion Notes

These are **deferred** design discussions captured during CS4 (multi-destination selection). They are not yet scheduled into a change set. Each item records the current behavior, the options considered, and the open questions, so the decision can be picked up cleanly in a later phase.

Format mirrors `next_milestone.md`. When an item is promoted to a real change set, move the agreed approach into `next_milestone.md`, implement it, and update the relevant ADR.

Status legend: **Deferred** = agreed to revisit later; **Open** = no decision yet.

---

## FS-1 — Visit order of selected stops

**Status:** Deferred. Current behavior accepted for now (see ADR-007).

**Current behavior (as of CS4):**
- The visit order is the position of each place in the `validated_candidates` list (i.e. N3 validation / N2 ranking order).
- The user's checkbox *click order* is not captured — `app.py` gathers selections by walking `range(len(candidates))` in ascending order, so the order is always list order.
- `confirm_selection` preserves that order into `selected_destinations`; N4 passes them to Google Routes as `intermediates` in that order.
- `optimizeWaypointOrder` is **not** set, so Google visits the stops exactly as given — no geographic optimization.

**Problem:**
- The order is essentially arbitrary relative to geography and can zig-zag (start → far → near → far). This inflates total travel time and makes the "doesn't fit in the trip window" case (and the resulting stop removals) more likely.

**Options considered:**
1. **Optimize geographically (Google-native).** Set `optimizeWaypointOrder: true` in the Routes request; Google returns `optimizedIntermediateWaypointIndex` and we reorder `selected_destinations` to match. Minimizes drive time, fewer removals. Requires adding `routes.optimizedIntermediateWaypointIndex` to the Routes field mask and a reorder step in N4. Trade-off: the order may differ from how the user picked them, and it ignores intent like "beach last for sunset" — so the UI must show the resulting sequence.
2. **User-controlled order.** Add an ordering control (drag / numbered) in the selection UI so the user explicitly sequences stops; N4 respects it exactly. More control, respects intent, but the user owns avoiding zig-zags. Requires capturing an explicit order list instead of `selected_indices` derived from list position.
3. **Hybrid.** Optimize by default, with a manual override toggle.
4. **Keep current** (candidate-list order). No change.

**Open questions:**
- Does ordering matter enough at the typical 2-stop trip, or only at 3 stops?
- If we optimize, do we ever need to honor an intent constraint (e.g. a "last stop" pin)?

**Recommendation to revisit with:** Option 1 (geo-optimize) as the default, with Option 3 (manual override) as a possible follow-up if users want intent control. Whichever is chosen, the final order must be surfaced in the UI.

---

## FS-2 — User-driven stop removal when a plan does not fit

**Status:** Deferred. Current behavior accepted for now (see ADR-007).

**Current behavior (as of CS4):**
- When N5 finds an error (e.g. total dwell + travel exceeds the trip window), it **automatically drops the last stop** in `selected_destinations`, writes a `removal_notice` explaining which stop was removed and why, and re-plans the remaining stops via N4. If none remain, it ends gracefully with `GRACEFUL_FAILURE_MESSAGE`.
- The user is informed *after* the fact; they do not choose which stop to drop.

**Desired behavior (future):**
- When a plan does not fit, **present the user their selected stops with enough information to decide what to remove** — at minimum: distance from start, travel time, and time-spent (dwell) per stop — plus the reason the plan does not fit.
- The user removes one (or more) stops; the plan is re-validated and re-prompts again if it still does not fit.

**Design sketch (for the later change set):**
- **N5:** on a fit/time error, stop auto-pruning. Instead, set a flag (e.g. `needs_user_pruning: bool`) and a reason message, and route control back to the selection/removal UI. Keep `selected_destinations` intact. Do not set `user_confirmed`.
- **State to surface per stop:** distance and one-way travel time come from the validated candidate (N3 wrote `travel_time_seconds`, `distance_meters`). "Time spent" (dwell) comes from N4's attempted `timeline` — so on this error path, **preserve the attempted timeline** rather than wiping it, so the UI can show planned dwell per stop.
- **App:** detect `needs_user_pruning`, render each selected stop as a card with distance / travel time / time-spent and a remove control, plus the not-fitting reason. On submit, update `selected_destinations` and re-run the pipeline.
- **Loop:** after the user removes a stop, re-validate; if it still does not fit, re-prompt with the updated list.

**Open questions:**
- Should removal be "pick what to remove" or "uncheck to keep" (mirror the selection gallery)?
- Should we still offer an "auto-fix for me" shortcut that falls back to the current last-stop-drop behavior?
- How do we show "time spent" if N4 could not produce a timeline at all (e.g. routing failure vs. time-overflow)? Likely fall back to N3 distance/travel-time only.

**Relationship to FS-1:** Better stop ordering (FS-1) reduces how often this removal flow is triggered at all, since a tighter route is more likely to fit. Consider sequencing FS-1 before FS-2.

---

## Notes

- These items were raised in the session that implemented CS4 (2026-06-09). They are intentionally **not** in `next_milestone.md` yet to avoid implying they are scheduled.
- The current CS4 decisions they supersede are recorded as **Accepted (current)** in `docs/adr/ADR-007-multi-destination-routing.md`, with these future revisits noted.
