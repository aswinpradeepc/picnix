# ADR-005: Dynamic Food Search from Route Geometry

**Status:** Accepted
**Date:** 2026-06-06

## Context

N4 needs to find food options for users who request a meal or are on a long remote route. An early approach would have used named route checkpoints (towns, highway junctions, known service areas) as static anchor points for restaurant search. The problem: static anchors are often far from the actual route, and they hardcode geographic assumptions into node prompts and Python constants.

## Decision

Derive food search coordinates dynamically from route geometry and the expected timeline position at meal time. Decode the encoded polyline from the Routes API response, sample a point along the line at the fraction of the trip corresponding to when the meal window opens, and search Google Places around that point.

Implemented in `n4_route.py` via `_point_on_polyline()` and `_route_point_for_meal()`. Food can be placed in one of three segments: outbound leg, time at destination, or return leg.

## Options Considered

- **Static named checkpoints**: List known route towns for Kerala trips (Thrissur, Palakkad, Kottayam, etc.) and pick the nearest one to each meal window. Simple. But hardcodes geography, gives wrong results for unusual routes, and requires maintenance as roads change.
- **Static destination radius**: Always search near the destination. Works for food-oriented trips but places breakfast recommendations at the destination even if the user departs at 5am and arrives at 8am.
- **Dynamic from route geometry (chosen)**: The fraction of the trip elapsed at meal time is computed from real durations (Routes API seconds). The polyline point is decoded from the API's encoded polyline. Search radius is fixed at a practical walking/driving distance. Result: the search center tracks the user's actual position at meal time, regardless of route.

## Consequences

- `_decode_polyline()` in `n4_route.py` handles the encoded polyline format returned by Routes API. If the polyline is absent (API error), it falls back to a straight-line interpolation between start and destination.
- Food guidance can be one of five statuses: `eat_at_destination`, `destination_options`, `route_options`, `eat_at_home`, `carry_or_parcel`. This avoids forcing a restaurant stop when one is not needed.
- The design explicitly prohibits static route towns, hubs, cities, or checkpoints in N4. This rule is enforced in `docs/design-context.md` and `docs/superpowers/status.md` as a fixed limit.
- If `search_food_spots_near_location` returns no results (remote area, early hours), the fallback is `carry_or_parcel` guidance — honest about the gap rather than inventing a restaurant.
