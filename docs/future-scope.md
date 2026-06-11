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

## FS-3 — Edit-time additions: on-demand place validation + user-directed food stops

**Status:** Deferred, scope agreed 2026-06-10. Current behavior accepted for now (see ADR-008).

**Current behavior (as of CS5):**
- N8 plan edits draw from a **closed universe**: `selected_destinations` ∪ `validated_candidates`, keyed by `place_id`.
- An edit asking for a place or category outside that pool (e.g. "add Kadamakudy lake view point" when it was never validated) is **not fulfilled**. N8 records it in the edit's `unfulfilled` list with reason "not in the validated pool for this trip", surfaces it via `edit_notice`, and leaves the rest of the edit applied. Nothing is invented and the user is never silently switched.
- Food planning is entirely N4's: `food_stops` / `food_availability` are re-derived from the route geometry on every re-plan. N8 cannot honor "have dinner at Pathirakozhi, Kalamassery" even when the restaurant is real and on the route — food requests are reported as unfulfilled like any out-of-pool place.

**Problem:**
- The validated pool only contains what N2/N3 fetched for the original constraints. Perfectly plannable places the user names mid-edit are rejected simply because they were never run through validation.
- Users know specific food spots they want; a food edit that can only say "couldn't do it" undercuts the editor for one of the most common real requests.

**Agreed direction (to spec when promoted to a change set):**
1. **New places can be added to the trip via edits.** When an edit names a place outside the pool, resolve it (Places text search) and run it through the same checks N3 applies (opening hours during the window, travel time, known issues). If it passes, add it to the plan **and** to `validated_candidates` so later edits can reuse it; if it fails, tell the user exactly why instead of "not in the validated pool".
2. **Food edits update the food plan.** A food-place edit ("dinner at Pathirakozhi, Kalamassery") validates the named food place and **pins** it into the food plan for that meal, overriding N4's route-derived choice. N4 must respect pinned food stops on every subsequent re-plan (likely a new state field, e.g. `pinned_food_stops`, that `_plan_food_availability` consults before searching the route).

**Options to consider for the mechanism:**
1. **N8 → N3 re-entry.** Route unfulfilled place requests back through the existing validation node, then re-run the edit. Reuses N3 wholesale but is a graph-topology change (a cycle into the N3 loop from the edit path) and re-opens the N4 interrupt dispatch rules. Does not cover food stops (N3 validates destinations, not meals).
2. **Targeted validation helpers called from N8's enforcement step.** Bounded "validate exactly this place" / "validate exactly this food stop" helpers (Places text search + hours + travel-time check) invoked only for named places, keeping the graph shape unchanged. Amends the current "N8 is LLM + state surgery only" rule (ADR-008), so the ADR needs an update when this ships. Covers both new stops and pinned food stops with one mechanism.

**Open questions:**
- How to resolve a free-text place name to a `place_id` safely (text search ranking vs. asking the user to confirm among top matches)?
- For pinned food stops: what happens when the pinned place is closed at the meal time or too far off the route — refuse the pin with a reason, or accept and warn?
- Does a pinned food stop survive a stop-removal replan (N5 drops a destination and N4 re-derives food)?

---

## Notes

- These items were raised in the session that implemented CS4 (2026-06-09). They are intentionally **not** in `next_milestone.md` yet to avoid implying they are scheduled.
- The current CS4 decisions they supersede are recorded as **Accepted (current)** in `docs/adr/ADR-007-multi-destination-routing.md`, with these future revisits noted.

---

## FS-4 — User-pinned destinations & schedule negotiation

**Today:** Every destination comes out of N2 discovery. The user can only choose from what N2/N3 surface. If the user *names* places up front ("start from CUSAT, go to Malayattoor, then Speedway Thrissur, eat at Thomson Casa"), N1 has nowhere to put them — they become "interests" at best and are lost.

**Desired behavior:**
- N1 extracts named places as **pinned stops** (a new constraint class, distinct from interests): `pinned_stops: [{query_text, role}]` where `role` is `visit` or `meal`.
- A resolution step (N2 or a new N2b) converts each `query_text` into a real place via Places Text Search → place_id, then routes it through the **same N3 validation** as discovered candidates (hours, travel time, known issues). Pinned places get no validation shortcuts.
- N4 plans all pinned stops into one timeline so that each stop's open hours and any meal window are satisfied — i.e., the timings of all pinned places "fall in place".
- **Infeasibility is negotiated, never silently resolved.** If no ordering/timing makes the pinned set fit, the system must come back to the user with concrete options: (a) drop a named stop (showing which one and the time it would free), or (b) shift `departure_time` / extend `duration_hours` by a stated amount that *would* make it fit. The user chooses. This is the pinned-stop analogue of FS-2 and should reuse its interactive-removal surface.
- A pinned stop that fails N3 validation (permanently closed, closed that day, unreachable) is reported by name with the reason. The system may *offer* a similar nearby alternative, but never substitutes one silently — same principle as the N5 no-silent-switch rule.

**Considerations:**
- Resolution ambiguity: "Speedway Thrissur" may match multiple places; low-confidence matches need a one-tap "did you mean…" confirmation in the interrupt UI before planning.
- Ordering: with 3+ pinned stops, visit order materially affects feasibility. FS-4 effectively requires FS-1 (order optimization) first — testing permutations against open-hours windows is the core of "make the timings fall in place".
- Meal-pinned stops ("food from Thomson Casa") are a hard food_availability entry: N4's dynamic food search is skipped for that meal and replaced by an open-hours/timing check on the named restaurant.
- Mixed mode: pinned stops + "and suggest one more place on the way" means discovery (N2) must fill gaps *around* fixed anchors — discovery becomes constrained by the pinned skeleton's geometry and leftover time, not a free radius.
- Time-window pins ("reach X by 2pm") are a natural extension: per-stop hard arrival windows checked in N4/N5.

**Touches:** N1 (extraction), N2/new N2b (resolution), N3 (validate pinned), N4 (windowed scheduling), N5 (negotiation path instead of auto-drop for pinned stops), interrupt UI, `TripState` (`pinned_stops`, per-stop time windows).

**Sequencing:** FS-1 → FS-2 → FS-4. FS-4's negotiation UX is FS-2 generalized.

---

## FS-5 — Open-jaw trips (start ≠ end) with on-route discovery

**Today:** Every plan is a round trip — N2's reachable radius, N4's `start → stops → start` chaining, and N7's pins all assume the user returns to the start point.

**Desired behavior:**
- N1 accepts an optional `end_location` distinct from `start_location` ("start from CUSAT, end at College of Engineering TVM, spend time somewhere in between").
- Time budgeting changes: available exploration time = `duration_hours − travel(start→end via stops)`. The baseline direct travel time start→end is computed first; what remains is the budget for dwell + detour.
- Discovery changes from a radius around the start to a **corridor along the start→end route**: compute the direct route polyline, sample points along it (reuse the ADR-005 `_point_on_polyline` machinery — same primitive, different purpose), and run Places searches around those samples. Candidates are scored by detour cost (added travel time vs. the direct route), not distance from start.
- N4 builds `start → stops → end` with no return leg; N7 renders distinct start and end pins and drops the "return home" timeline entry.

**Considerations:**
- The `(duration_hours − 2) / 2` one-way radius formula in N2 is meaningless here and needs a corridor-specific replacement (e.g., max detour minutes per stop).
- "On the way" is directional — a great place 10 min *behind* the start is a bad suggestion; detour-cost scoring handles this naturally where radius scoring cannot.
- Round trip becomes the special case `end_location == start_location`; ideally the corridor model subsumes the current radius model rather than living beside it.
- Combines with FS-4: open-jaw + pinned stops ("CUSAT → Malayattoor → end in TVM") is the general case — pinned anchors define the corridor segments, discovery fills between them.

**Touches:** N1 (end_location), N2 (corridor discovery + scoring), N4 (open-jaw chaining), N5 (time checks against arrival-at-end), N7 (start/end pins), `TripState` (`constraints["end_location"]`).

---

## FS-6 — Candidate cases to fold into FS-4/FS-5 when designed (parking list)

- **Anchor-last planning:** "end with dinner at <named place>" — a single pinned terminal stop, everything before it discovered. Cheapest first slice of FS-4.
- **Via-only waypoints:** "go via the Athirappilly road" — a route shaping constraint with zero dwell time, distinct from a stop.
- **Per-stop arrival deadlines:** "be at the church before 9am mass" — hard time windows, superset of open-hours checks.
- **Pinned stop on a different day's schedule:** user names a place that's closed today; offer the nearest day it works instead of just rejecting (requires multi-day awareness — likely out of scope until the multiday graph exists).
- **Return-by constraint:** "I must be back by 6pm" as a hard end-of-trip deadline rather than a soft duration — N5 should treat overrun as `error`, not `warning`.

---

## FS-7 — Arize AX production observability

**Status:** Deferred. Phoenix is the active observability target for ADR-009.

**Current behavior:**
- Observability is Phoenix-first and opt-in via `OBSERVABILITY_ENABLED=true` and `ARIZE_PRODUCT=phoenix`.
- `app.py` installs OpenInference LangChain instrumentation globally before LangGraph/LangChain imports.
- Manual node/tool spans are intentionally deferred.

**Desired behavior:**
- Promote observability to Arize AX when Picnix has the backend, user/session model, and deployment surface needed for production operations.
- Add AX environment variables, exporter configuration, dashboards, and production monitoring workflows.
- Define which trace attributes become product metrics (success/failure, validation rejections, route build latency, edit success, user-visible fallback paths).

**Open questions:**
- What production identity should traces carry once user management exists: anonymous session ID, user ID, trip ID, or all three?
- Which trace content, if any, may be retained in production?
- Should AX adoption happen before or after the FastAPI/backend milestone?

**Touches:** observability bootstrap, environment configuration, deployment secrets, backend request/session IDs, privacy policy, dashboards/alerts.
