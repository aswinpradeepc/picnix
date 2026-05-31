from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from config.settings import SETTINGS, Settings
from graph.state import TripState
from tools import gmaps


KNOWN_RESTRICTED_PLACE_NOTES = {
    "anamudi peak": "permit required, check DFO office",
    "eravikulam np": "seasonal closure Feb-Mar for nilgiri tahr calving",
}


def _trip_start_default() -> datetime:
    now = datetime.now()
    start = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if now > start:
        start += timedelta(days=1)
    return start


def _max_one_way_seconds(duration_hours: float) -> int:
    return int(max((duration_hours - 2) / 2, 0.5) * 3600)


def _failure(
    state: TripState,
    candidate: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "candidate_index": int(state.get("candidate_index", 0)) + 1,
        "validation_failures": [
            *list(state.get("validation_failures", [])),
            f"{candidate.get('name', 'candidate')} rejected: {reason}",
        ],
    }


def _notes_for_candidate(candidate: dict[str, Any]) -> list[str]:
    name = str(candidate.get("name", "")).strip().lower()
    notes = list(candidate.get("notes", []))
    for restricted_name, note in KNOWN_RESTRICTED_PLACE_NOTES.items():
        if restricted_name == name and note not in notes:
            notes.append(note)
    return notes


def validate_destination(
    state: TripState,
    *,
    settings: Settings = SETTINGS,
    gmaps_client: Any = gmaps,
    trip_start: datetime | None = None,
) -> dict[str, Any]:
    """Read the current candidate and validation context, then write either `validated_destination` or the next `candidate_index` with a failure reason."""
    candidates = list(state.get("candidates", []))
    candidate_index = int(state.get("candidate_index", 0))
    if candidate_index >= len(candidates):
        return {
            "validation_failures": [
                *list(state.get("validation_failures", [])),
                "No destination candidates remain.",
            ]
        }

    candidate = candidates[candidate_index]
    details = gmaps_client.get_place_details(candidate["place_id"], settings=settings)
    if details.get("business_status") == "CLOSED_PERMANENTLY":
        return _failure(state, candidate, "permanently closed")

    duration_hours = float(state["constraints"]["duration_hours"])
    window_start = trip_start or _trip_start_default()
    window_end = window_start + timedelta(hours=duration_hours)
    if not gmaps_client.validate_place_open_for_window(details, window_start, window_end):
        return _failure(state, candidate, "closed during trip window")

    center = state["isochrone_polygon"]["properties"]["center"]
    route = gmaps_client.compute_route(
        origin=center,
        destination=candidate["coords"],
        settings=settings,
    )
    max_allowed = int(_max_one_way_seconds(duration_hours) * 1.3)
    travel_time = int(route.get("duration_seconds", 0))
    if travel_time > max_allowed:
        return _failure(
            state,
            candidate,
            f"travel time {travel_time}s exceeds allowed {max_allowed}s",
        )

    validated_destination = {
        **candidate,
        **details,
        "coords": candidate["coords"],
        "travel_time_seconds": travel_time,
        "distance_meters": route.get("distance_meters", 0),
        "route_preview": route,
        "notes": _notes_for_candidate(candidate),
    }
    return {
        "validated_destination": validated_destination,
        "validation_failures": list(state.get("validation_failures", [])),
        "candidate_index": candidate_index,
    }
