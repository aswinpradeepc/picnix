# ADR-007: Multi-destination Routing & Stop Selection

**Status:** Accepted
**Date:** 2026-06-09

## Context

CS4 lets the user pick up to 3 destinations for a single trip, where the planner previously supported exactly one. This required decisions on three points: (1) how to compute a route through multiple stops, (2) what order to visit them in, and (3) what to do when the selected stops do not fit the trip window. Two of these (order, removal UX) have agreed future revisits, captured in `docs/future-scope.md` (FS-1, FS-2). This ADR records what was decided and implemented for CS4.

## Decision

**1. Routing — single `computeRoutes` call with intermediate waypoints.**
N4 chains `start → dest1 → … → destN → start` in **one** Google Routes `computeRoutes` request, passing the stops as `intermediates`. `tools/gmaps.compute_route` gained an optional `intermediates` parameter and returns `normalized_legs` (per-hop distance / duration / encoded polyline) so N4 can build a unified timeline and place per-segment food. The full-route polyline drives the map LineString; the per-leg data drives timing.

**2. Visit order — candidate-list order, no optimization (current).**
Stops are visited in the order they appear in `validated_candidates` (N3 validation / N2 ranking order). `optimizeWaypointOrder` is not set. The user's checkbox click order is not captured. See FS-1 for the deferred decision to geo-optimize or allow user ordering.

**3. Stop removal — N5 auto-drops the last stop and re-plans (current).**
When N5 finds a fit/time error, it removes the last stop from `selected_destinations`, records a user-facing `removal_notice`, resets the route artifacts, and re-plans the remaining stops via N4. If none remain, it ends gracefully. See FS-2 for the deferred decision to make removal user-driven.

## Options Considered

### Routing
- **Per-leg stitching:** call `compute_route` once per hop (`start→A`, `A→B`, …) and glue the responses. Reuses the existing point-to-point helper and keeps legs cleanly separated, but issues N+1 API calls and was felt to be the wrong primitive for a single logical route.
- **Single call with `intermediates` (chosen):** one request, one route, Google returns one leg per hop. Fewer calls, native multi-waypoint semantics, and the per-leg breakdown is still available via `normalized_legs`. Cost: the food/timing code had to be generalized from a fixed outbound/inbound pair to an arbitrary ordered list of legs.

### Visit order
- **Geo-optimize via `optimizeWaypointOrder`:** shortest round trip, fewer "doesn't fit" cases, but order may not match user intent. Deferred (FS-1, recommended default for the later phase).
- **User-controlled order:** respects intent, but needs new UI and shifts zig-zag avoidance to the user. Deferred (FS-1).
- **Candidate-list order (chosen for now):** zero added UI/complexity; ships CS4. Accepted as the interim behavior.

### Stop removal
- **User-driven removal:** present the stops with distance / travel time / time-spent and let the user choose. Better UX; needs an interactive prune interrupt and preserved per-stop timing. Deferred (FS-2).
- **Auto-drop last stop (chosen for now):** deterministic, no extra UI, keeps the replan loop simple. The last stop is the one most likely to be overflowing the time budget. Accepted as the interim behavior, with `removal_notice` keeping the user informed.

## Consequences

- State model changed: `selected_destinations: list[dict]` (+ `max_destinations`, `presented_candidate_indices`, `removal_notice`) replaced `validated_destination` / `presented_candidate_index`. N4/N5/N7 iterate over the list; N7 labels each stop "Stop N".
- The Streamlit selection surface is now a scrollable multi-select card gallery with "Confirm selection" and "Load more options".
- Routing uses `routes.legs` from the existing field mask. Geo-optimization (FS-1) would additionally require `routes.optimizedIntermediateWaypointIndex` in the field mask and a reorder step in N4.
- Because order is not optimized, zig-zag routes are possible and increase the likelihood of the auto-removal path firing. FS-1 and FS-2 are related and should ideally be sequenced FS-1 → FS-2.
- The interim auto-removal means the user is told *which* stop was dropped and *why* (`removal_notice`) but does not choose. FS-2 supersedes this once scheduled; the attempted timeline would need to be preserved on the error path to show per-stop "time spent".
