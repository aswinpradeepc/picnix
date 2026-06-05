from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from config.settings import SETTINGS, Settings
from graph.nodes.time_utils import trip_start_from_constraints
from graph.state import TripState
from tools import gmaps


FOOD_STOP_THRESHOLD_SECONDS = 90 * 60
FOOD_STOP_DURATION_SECONDS = 45 * 60
FOOD_STOP_SEARCH_LIMIT = 5
MIN_FOOD_STOP_RATING = 4.0
FOOD_STOP_TYPES = {"restaurant", "cafe"}


def _format_time(value: datetime) -> str:
    return value.strftime("%H:%M")


def _format_duration(seconds: int) -> str:
    minutes = round(seconds / 60)
    hours, remaining_minutes = divmod(minutes, 60)
    if hours and remaining_minutes:
        return f"{hours} hr {remaining_minutes} min"
    if hours:
        return f"{hours} hr"
    return f"{remaining_minutes} min"


def _line_coords(coords: dict[str, float]) -> list[float]:
    return [float(coords["lng"]), float(coords["lat"])]


def _travel_mode(vehicle: str) -> str:
    if vehicle == "bike":
        return "TWO_WHEELER"
    return "DRIVE"


def _decode_polyline(encoded: str) -> list[list[float]]:
    if not encoded:
        return []

    try:
        coordinates: list[list[float]] = []
        index = 0
        lat = 0
        lng = 0

        while index < len(encoded):
            shift = 0
            result = 0
            while True:
                value = ord(encoded[index]) - 63
                index += 1
                result |= (value & 0x1F) << shift
                shift += 5
                if value < 0x20:
                    break
            lat += ~(result >> 1) if result & 1 else result >> 1

            shift = 0
            result = 0
            while True:
                value = ord(encoded[index]) - 63
                index += 1
                result |= (value & 0x1F) << shift
                shift += 5
                if value < 0x20:
                    break
            lng += ~(result >> 1) if result & 1 else result >> 1
            coordinates.append([round(lng / 1e5, 5), round(lat / 1e5, 5)])
    except (IndexError, ValueError):
        return []

    return coordinates


def _route_coordinates(
    *,
    start: dict[str, float],
    destination: dict[str, float],
    outbound: dict[str, Any],
    inbound: dict[str, Any],
) -> list[list[float]]:
    outbound_points = _decode_polyline(outbound.get("encoded_polyline", ""))
    inbound_points = _decode_polyline(inbound.get("encoded_polyline", ""))
    if not outbound_points and not inbound_points:
        return [_line_coords(start), _line_coords(destination), _line_coords(start)]
    if outbound_points and inbound_points:
        return [*outbound_points, *inbound_points[1:]]
    if outbound_points:
        return [*outbound_points, _line_coords(start)]
    return [_line_coords(start), *inbound_points]


def _timeline_entry(
    *,
    time_value: datetime,
    label: str,
    coords: dict[str, float],
    entry_type: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "time": _format_time(time_value),
        "label": label,
        "coords": coords,
        "type": entry_type,
        "notes": notes,
    }


def _is_food_candidate(candidate: dict[str, Any]) -> bool:
    if float(candidate.get("rating") or 0) < MIN_FOOD_STOP_RATING:
        return False
    candidate_types = set(candidate.get("types", []))
    primary_type = candidate.get("primary_type")
    if primary_type:
        candidate_types.add(primary_type)
    return bool(candidate_types.intersection(FOOD_STOP_TYPES))


def _food_label(stop_start: datetime) -> str:
    return "Breakfast stop" if stop_start.hour < 11 else "Lunch stop"


def _select_food_stop(
    *,
    outbound_route: dict[str, Any],
    trip_start: datetime,
    gmaps_client: Any,
    settings: Settings,
) -> dict[str, Any] | None:
    route_polyline = outbound_route.get("encoded_polyline", "")
    if not route_polyline:
        return None

    outbound_seconds = int(outbound_route.get("duration_seconds", 0))
    stop_start = trip_start + timedelta(seconds=outbound_seconds // 2)
    stop_end = stop_start + timedelta(seconds=FOOD_STOP_DURATION_SECONDS)

    for candidate in gmaps_client.search_food_stops_along_route(
        route_polyline=route_polyline,
        settings=settings,
        max_results=FOOD_STOP_SEARCH_LIMIT,
    ):
        if not _is_food_candidate(candidate):
            continue

        details = gmaps_client.get_place_details(candidate["place_id"], settings=settings)
        combined = {
            **candidate,
            **details,
            "coords": candidate.get("coords") or details.get("coords", {}),
            "rating": candidate.get("rating") or details.get("rating"),
            "types": candidate.get("types") or details.get("types", []),
        }
        if not gmaps_client.validate_place_open_for_window(combined, stop_start, stop_end):
            continue

        return {
            **combined,
            "stop_start": _format_time(stop_start),
            "stop_end": _format_time(stop_end),
            "planned_duration_seconds": FOOD_STOP_DURATION_SECONDS,
            "notes": f"{_food_label(stop_start)} on the way.",
        }

    return None


def build_route(
    state: TripState,
    *,
    settings: Settings = SETTINGS,
    gmaps_client: Any = gmaps,
    trip_start: datetime | None = None,
) -> dict[str, Any]:
    """Read the confirmed destination and trip constraints, then write the round-trip `route`, validated `food_stops`, and ordered `timeline` for N5/N7."""
    destination = dict(state.get("validated_destination", {}))
    if not destination:
        return {"route": {}, "food_stops": [], "timeline": []}

    constraints = state["constraints"]
    start = state["isochrone_polygon"]["properties"]["center"]
    start_label = str(constraints.get("start_location") or "Start")
    destination_coords = destination["coords"]
    destination_label = str(destination.get("name") or "Destination")
    duration_hours = float(constraints["duration_hours"])
    travel_mode = _travel_mode(str(constraints.get("vehicle", "none")))
    departure = trip_start or trip_start_from_constraints(constraints)

    outbound = gmaps_client.compute_route(
        origin=start,
        destination=destination_coords,
        settings=settings,
        travel_mode=travel_mode,
    )
    inbound = gmaps_client.compute_route(
        origin=destination_coords,
        destination=start,
        settings=settings,
        travel_mode=travel_mode,
    )

    outbound_seconds = int(outbound.get("duration_seconds", 0))
    inbound_seconds = int(inbound.get("duration_seconds", 0))
    total_travel_seconds = outbound_seconds + inbound_seconds

    food_stop = None
    if outbound_seconds > FOOD_STOP_THRESHOLD_SECONDS:
        food_stop = _select_food_stop(
            outbound_route=outbound,
            trip_start=departure,
            gmaps_client=gmaps_client,
            settings=settings,
        )

    food_stop_seconds = FOOD_STOP_DURATION_SECONDS if food_stop else 0
    destination_seconds = max(
        int(duration_hours * 3600) - total_travel_seconds - food_stop_seconds,
        0,
    )

    food_stop_start = (
        departure + timedelta(seconds=outbound_seconds // 2) if food_stop else None
    )
    arrival_at_destination = departure + timedelta(
        seconds=outbound_seconds + food_stop_seconds
    )
    depart_destination = arrival_at_destination + timedelta(seconds=destination_seconds)
    return_arrival = depart_destination + timedelta(seconds=inbound_seconds)

    timeline = [
        _timeline_entry(
            time_value=departure,
            label=f"Depart {start_label}",
            coords=start,
            entry_type="start",
            notes="Start the trip.",
        )
    ]
    waypoints = [
        {
            "label": start_label,
            "coords": start,
            "type": "start",
            "eta": _format_time(departure),
        }
    ]

    if food_stop and food_stop_start:
        food_stop_label = str(food_stop.get("name") or "Food stop")
        timeline.append(
            _timeline_entry(
                time_value=food_stop_start,
                label=food_stop_label,
                coords=food_stop["coords"],
                entry_type="food",
                notes=food_stop["notes"],
            )
        )
        waypoints.append(
            {
                "label": food_stop_label,
                "coords": food_stop["coords"],
                "type": "food",
                "eta": food_stop["stop_start"],
                "notes": food_stop["notes"],
            }
        )

    timeline.extend(
        [
            _timeline_entry(
                time_value=arrival_at_destination,
                label=destination_label,
                coords=destination_coords,
                entry_type="destination",
                notes=f"Spend {_format_duration(destination_seconds)} here.",
            ),
            _timeline_entry(
                time_value=depart_destination,
                label=f"Leave {destination_label}",
                coords=destination_coords,
                entry_type="return_departure",
                notes="Start the return journey.",
            ),
            _timeline_entry(
                time_value=return_arrival,
                label=f"Back at {start_label}",
                coords=start,
                entry_type="return",
                notes="Trip ends.",
            ),
        ]
    )
    waypoints.extend(
        [
            {
                "label": destination_label,
                "coords": destination_coords,
                "type": "destination",
                "eta": _format_time(arrival_at_destination),
                "notes": destination.get("description", ""),
            },
            {
                "label": start_label,
                "coords": start,
                "type": "return",
                "eta": _format_time(return_arrival),
            },
        ]
    )

    route = {
        "geojson": {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": _route_coordinates(
                    start=start,
                    destination=destination_coords,
                    outbound=outbound,
                    inbound=inbound,
                ),
            },
            "properties": {
                "type": "route",
                "distance_meters": int(outbound.get("distance_meters", 0))
                + int(inbound.get("distance_meters", 0)),
                "travel_duration_seconds": total_travel_seconds,
            },
        },
        "waypoints": waypoints,
        "legs": [
            {
                "type": "outbound",
                "from": start_label,
                "to": destination_label,
                "distance_meters": int(outbound.get("distance_meters", 0)),
                "duration_seconds": outbound_seconds,
                "depart_time": _format_time(departure),
                "arrive_time": _format_time(arrival_at_destination),
                "steps": outbound.get("legs", []),
            },
            {
                "type": "return",
                "from": destination_label,
                "to": start_label,
                "distance_meters": int(inbound.get("distance_meters", 0)),
                "duration_seconds": inbound_seconds,
                "depart_time": _format_time(depart_destination),
                "arrive_time": _format_time(return_arrival),
                "steps": inbound.get("legs", []),
            },
        ],
        "encoded_polylines": {
            "outbound": outbound.get("encoded_polyline", ""),
            "return": inbound.get("encoded_polyline", ""),
        },
        "total_distance_meters": int(outbound.get("distance_meters", 0))
        + int(inbound.get("distance_meters", 0)),
        "travel_duration_seconds": total_travel_seconds,
        "planned_duration_seconds": int((return_arrival - departure).total_seconds()),
        "raw": {"outbound": outbound, "return": inbound},
    }

    return {
        "route": route,
        "food_stops": [food_stop] if food_stop else [],
        "timeline": timeline,
    }
