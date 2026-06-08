from __future__ import annotations

import json
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import SETTINGS, Settings
from graph.nodes.time_utils import trip_start_from_constraints
from graph.state import TripState
from tools import gmaps
from tools.vertex import REASONING_GEMINI_MODEL, get_chat_model


EARTH_RADIUS_KM = 6371.0088
MIN_DWELL_SECONDS = 20 * 60
DEFAULT_DWELL_SECONDS = 60 * 60
FOOD_STOP_THRESHOLD_SECONDS = 90 * 60
FOOD_STOP_DURATION_SECONDS = 45 * 60
DINNER_STOP_DURATION_SECONDS = 75 * 60
FOOD_SEARCH_LIMIT = 5
MIN_FOOD_RATING = 4.0
FOOD_TYPES = {"restaurant", "cafe", "meal_takeaway", "bakery", "food"}
DINNER_KEYWORDS = {"dinner", "supper"}
LUNCH_KEYWORDS = {"lunch"}
BREAKFAST_KEYWORDS = {"breakfast"}
REMOTE_DESTINATION_TYPES = {
    "beach",
    "campground",
    "hiking_area",
    "nature_preserve",
    "park",
    "scenic_spot",
}
MEAL_ANCHOR_HOURS = {
    "breakfast": 9,
    "lunch": 13,
    "dinner": 19,
}


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


def _coords_from_line(value: list[float]) -> dict[str, float]:
    return {"lat": float(value[1]), "lng": float(value[0])}


def _distance_km(start: dict[str, float], end: dict[str, float]) -> float:
    start_lat = radians(start["lat"])
    end_lat = radians(end["lat"])
    delta_lat = radians(end["lat"] - start["lat"])
    delta_lng = radians(end["lng"] - start["lng"])
    value = (
        sin(delta_lat / 2) ** 2
        + cos(start_lat) * cos(end_lat) * sin(delta_lng / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(value))


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


def _interpolate_coords(
    start: dict[str, float],
    end: dict[str, float],
    fraction: float,
) -> dict[str, float]:
    clamped = max(0.0, min(1.0, fraction))
    return {
        "lat": start["lat"] + (end["lat"] - start["lat"]) * clamped,
        "lng": start["lng"] + (end["lng"] - start["lng"]) * clamped,
    }


def _point_on_polyline(points: list[list[float]], fraction: float) -> dict[str, float]:
    if not points:
        raise ValueError("Cannot sample an empty route polyline.")
    if len(points) == 1:
        return _coords_from_line(points[0])

    segments: list[tuple[dict[str, float], dict[str, float], float]] = []
    total_distance = 0.0
    for index in range(len(points) - 1):
        start = _coords_from_line(points[index])
        end = _coords_from_line(points[index + 1])
        distance = _distance_km(start, end)
        segments.append((start, end, distance))
        total_distance += distance

    if total_distance <= 0:
        return _coords_from_line(points[0])

    target_distance = total_distance * max(0.0, min(1.0, fraction))
    travelled = 0.0
    for start, end, distance in segments:
        if travelled + distance >= target_distance:
            segment_fraction = (target_distance - travelled) / distance if distance else 0
            return _interpolate_coords(start, end, segment_fraction)
        travelled += distance

    return _coords_from_line(points[-1])


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


def _state_text(state: TripState) -> str:
    parts: list[str] = []
    for message in state.get("raw_messages", []):
        parts.append(str(message.get("content", "")))
    parts.extend(str(interest) for interest in state.get("constraints", {}).get("interests", []))
    return " ".join(parts).lower()


def _destination_types(destination: dict[str, Any]) -> set[str]:
    destination_types = set(destination.get("types", []))
    primary_type = destination.get("primary_type")
    if primary_type:
        destination_types.add(primary_type)
    return destination_types


def _is_food_candidate(candidate: dict[str, Any]) -> bool:
    if float(candidate.get("rating") or 0) < MIN_FOOD_RATING:
        return False
    candidate_types = set(candidate.get("types", []))
    primary_type = candidate.get("primary_type")
    if primary_type:
        candidate_types.add(primary_type)
    return bool(candidate_types.intersection(FOOD_TYPES))


def _destination_is_food_oriented(destination: dict[str, Any]) -> bool:
    return bool(_destination_types(destination).intersection(FOOD_TYPES))


def _destination_is_remote(destination: dict[str, Any]) -> bool:
    return bool(_destination_types(destination).intersection(REMOTE_DESTINATION_TYPES))


def _explicit_meals(state: TripState) -> list[str]:
    text = _state_text(state)
    meals: list[str] = []
    if any(keyword in text for keyword in BREAKFAST_KEYWORDS):
        meals.append("breakfast")
    if any(keyword in text for keyword in LUNCH_KEYWORDS):
        meals.append("lunch")
    if any(keyword in text for keyword in DINNER_KEYWORDS):
        meals.append("dinner")
    return meals


def _meal_time(meal: str, departure: datetime) -> datetime:
    value = departure.replace(
        hour=MEAL_ANCHOR_HOURS[meal],
        minute=0,
        second=0,
        microsecond=0,
    )
    if value < departure:
        value += timedelta(days=1)
    return value


def _meal_duration(meal: str) -> int:
    if meal == "dinner":
        return DINNER_STOP_DURATION_SECONDS
    return FOOD_STOP_DURATION_SECONDS


def _food_label(meal: str) -> str:
    return f"{meal.title()} options"


DWELL_TIME_SYSTEM_PROMPT = """You are a trip timing expert. Given one or more destinations and trip constraints, decide how many minutes a group should spend at each destination.

Return a JSON array with exactly one object per destination:
[{"place_id": "...", "dwell_minutes": <integer>, "reason": "<one sentence explaining the recommendation>"}]

Base your answer on: destination type, interests alignment, group size, budget feel, and total available time.
Nature parks, beaches, and hiking areas warrant longer stays than temples, museums, or shopping stops.
When several destinations share the day, balance the minutes so the whole trip fits the available time.
Always return dwell_minutes as a plain integer with no unit suffix.
"""


def _ceiling_dwell_seconds(
    duration_hours: float,
    total_travel_seconds: int,
    num_destinations: int,
) -> int:
    available = max(int(duration_hours * 3600) - total_travel_seconds, 0)
    return max(MIN_DWELL_SECONDS, available // max(num_destinations, 1))


def _parse_dwell_entries(content: Any) -> list[dict[str, Any]]:
    raw = content if isinstance(content, str) else str(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
        else:
            raise
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("Dwell-time response is not a list.")
    return [item for item in data if isinstance(item, dict)]


def _llm_dwell_times(
    *,
    destinations: list[dict[str, Any]],
    constraints: dict[str, Any],
    duration_hours: float,
    total_travel_seconds: int,
    model: Any,
) -> list[tuple[int, str]]:
    num_destinations = len(destinations)
    ceiling = _ceiling_dwell_seconds(duration_hours, total_travel_seconds, num_destinations)
    payload = {
        "destinations": [
            {
                "place_id": destination.get("place_id", ""),
                "name": destination.get("name", ""),
                "primary_type": destination.get("primary_type", ""),
                "description": destination.get("description", ""),
            }
            for destination in destinations
        ],
        "constraints": {
            "group_size": constraints.get("group_size", 1),
            "vehicle": constraints.get("vehicle", "none"),
            "interests": constraints.get("interests", []),
            "budget_feel": constraints.get("budget_feel", "medium"),
            "duration_hours": duration_hours,
        },
        "num_destinations": num_destinations,
    }

    by_id: dict[str, tuple[int, str]] = {}
    ordered: list[tuple[int, str]] = []
    try:
        response = model.invoke([
            SystemMessage(content=DWELL_TIME_SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(payload, sort_keys=True)),
        ])
        for entry in _parse_dwell_entries(response.content):
            try:
                minutes = int(entry.get("dwell_minutes", 0))
            except (TypeError, ValueError):
                minutes = 0
            reason = str(entry.get("reason", "")).strip()
            place_id = str(entry.get("place_id", "")).strip()
            if place_id:
                by_id[place_id] = (minutes, reason)
            ordered.append((minutes, reason))
    except (json.JSONDecodeError, ValueError, KeyError, AttributeError):
        by_id, ordered = {}, []

    results: list[tuple[int, str]] = []
    for index, destination in enumerate(destinations):
        place_id = str(destination.get("place_id", "")).strip()
        if place_id and place_id in by_id:
            minutes, reason = by_id[place_id]
        elif index < len(ordered):
            minutes, reason = ordered[index]
        else:
            minutes, reason = DEFAULT_DWELL_SECONDS // 60, ""
        seconds = minutes * 60 if minutes > 0 else DEFAULT_DWELL_SECONDS
        clamped = max(MIN_DWELL_SECONDS, min(seconds, ceiling))
        results.append((clamped, reason))
    return results


def _leg_points(
    *,
    fallback_start: dict[str, float],
    fallback_end: dict[str, float],
    encoded_polyline: str,
) -> list[list[float]]:
    decoded = _decode_polyline(encoded_polyline)
    if decoded:
        return decoded
    return [_line_coords(fallback_start), _line_coords(fallback_end)]


def _search_food_near(
    *,
    center: dict[str, float],
    stop_start: datetime,
    duration_seconds: int,
    gmaps_client: Any,
    settings: Settings,
) -> list[dict[str, Any]]:
    if not hasattr(gmaps_client, "search_food_spots_near_location"):
        return []

    stop_end = stop_start + timedelta(seconds=duration_seconds)
    recommendations: list[dict[str, Any]] = []
    for candidate in gmaps_client.search_food_spots_near_location(
        center=center,
        settings=settings,
        max_results=FOOD_SEARCH_LIMIT,
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
        recommendations.append(
            {
                "place_id": combined.get("place_id", ""),
                "name": combined.get("name", ""),
                "rating": combined.get("rating"),
                "address": combined.get("address", ""),
                "coords": combined.get("coords", {}),
                "google_maps_uri": combined.get("google_maps_uri", ""),
            }
        )

    return recommendations


def _food_names(recommendations: list[dict[str, Any]]) -> str:
    names = [
        str(place.get("name", "")).strip()
        for place in recommendations
        if str(place.get("name", "")).strip()
    ]
    return ", ".join(names[:5])


def _availability_entry(
    *,
    meal: str,
    need: str,
    status: str,
    time_value: datetime,
    coords: dict[str, float],
    notes: str,
    recommended_places: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "meal": meal,
        "need": need,
        "status": status,
        "time": _format_time(time_value),
        "coords": coords,
        "notes": notes,
        "recommended_places": recommended_places or [],
    }


def _route_food_stop(
    *,
    meal: str,
    need: str,
    status: str,
    stop_start: datetime,
    duration_seconds: int,
    coords: dict[str, float],
    notes: str,
    recommended_places: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "place_id": "",
        "name": f"{_food_label(meal)} near route",
        "coords": coords,
        "rating": None,
        "types": ["food_guidance"],
        "primary_type": "food_guidance",
        "meal": meal,
        "need": need,
        "status": status,
        "recommended_places": recommended_places,
        "stop_start": _format_time(stop_start),
        "stop_end": _format_time(stop_start + timedelta(seconds=duration_seconds)),
        "planned_duration_seconds": duration_seconds,
        "notes": notes,
    }


def _build_segments(
    *,
    start: dict[str, float],
    stops: list[dict[str, Any]],
    legs: list[dict[str, Any]],
    departure: datetime,
    return_arrival: datetime,
) -> list[dict[str, Any]]:
    """Ordered list of `leg` (travel) and `dwell` (at a stop) phases used to place meals per segment."""
    segments: list[dict[str, Any]] = []
    prev_coords = start
    prev_time = departure
    for index, stop in enumerate(stops):
        leg = legs[index] if index < len(legs) else {}
        segments.append(
            {
                "kind": "leg",
                "depart": prev_time,
                "arrive": stop["arrive"],
                "points": _leg_points(
                    fallback_start=prev_coords,
                    fallback_end=stop["coords"],
                    encoded_polyline=leg.get("encoded_polyline", ""),
                ),
            }
        )
        segments.append(
            {
                "kind": "dwell",
                "start": stop["arrive"],
                "end": stop["depart"],
                "coords": stop["coords"],
                "destination": stop["destination"],
            }
        )
        prev_coords = stop["coords"]
        prev_time = stop["depart"]

    final_leg = legs[-1] if legs else {}
    segments.append(
        {
            "kind": "leg",
            "depart": prev_time,
            "arrive": return_arrival,
            "points": _leg_points(
                fallback_start=prev_coords,
                fallback_end=start,
                encoded_polyline=final_leg.get("encoded_polyline", ""),
            ),
        }
    )
    return segments


def _locate_meal(
    segments: list[dict[str, Any]],
    meal_time: datetime,
) -> tuple[str, dict[str, float], dict[str, Any] | None]:
    """Find which phase a meal time falls in. Returns (location_type, coords, destination)."""
    for segment in segments:
        if segment["kind"] == "dwell" and segment["start"] <= meal_time <= segment["end"]:
            return "destination", segment["coords"], segment["destination"]
        if segment["kind"] == "leg" and segment["depart"] <= meal_time <= segment["arrive"]:
            duration = max((segment["arrive"] - segment["depart"]).total_seconds(), 1)
            fraction = (meal_time - segment["depart"]).total_seconds() / duration
            return "leg", _point_on_polyline(segment["points"], fraction), None

    # Meal falls after the trip ends: anchor it near the end of the final leg.
    final_leg = next(
        (segment for segment in reversed(segments) if segment["kind"] == "leg"),
        None,
    )
    if final_leg:
        return "after", _point_on_polyline(final_leg["points"], 0.7), None
    return "after", segments[0].get("coords", {"lat": 0.0, "lng": 0.0}), None


def _plan_explicit_meal(
    *,
    meal: str,
    segments: list[dict[str, Any]],
    departure: datetime,
    gmaps_client: Any,
    settings: Settings,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    meal_time = _meal_time(meal, departure)
    duration_seconds = _meal_duration(meal)
    location_type, center, destination = _locate_meal(segments, meal_time)

    if location_type == "destination" and destination and _destination_is_food_oriented(destination):
        notes = (
            f"{destination.get('name', 'This stop')} is food-oriented, so plan "
            f"{meal} there instead of adding a separate restaurant stop."
        )
        return (
            _availability_entry(
                meal=meal,
                need="explicit",
                status="eat_at_destination",
                time_value=meal_time,
                coords=center,
                notes=notes,
            ),
            None,
        )

    recommendations = _search_food_near(
        center=center,
        stop_start=meal_time,
        duration_seconds=duration_seconds,
        gmaps_client=gmaps_client,
        settings=settings,
    )

    if recommendations:
        names = _food_names(recommendations)
        if location_type == "destination":
            status = "destination_options"
            notes = f"Food is available near this stop for {meal}. Google Maps options: {names}."
        else:
            status = "route_options"
            notes = f"Plan {meal} near this route segment. Google Maps options: {names}."
        availability = _availability_entry(
            meal=meal,
            need="explicit",
            status=status,
            time_value=meal_time,
            coords=center,
            notes=notes,
            recommended_places=recommendations,
        )
        food_stop = _route_food_stop(
            meal=meal,
            need="explicit",
            status=status,
            stop_start=meal_time,
            duration_seconds=duration_seconds,
            coords=center,
            notes=notes,
            recommended_places=recommendations,
        )
        return availability, food_stop

    notes = (
        f"Food availability for {meal} could not be confirmed near the stops or route. "
        "Carry water/snacks or pick up a parcel before leaving."
    )
    return (
        _availability_entry(
            meal=meal,
            need="explicit",
            status="carry_or_parcel",
            time_value=meal_time,
            coords=center,
            notes=notes,
        ),
        None,
    )


def _plan_food_availability(
    *,
    state: TripState,
    stops: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    departure: datetime,
    return_arrival: datetime,
    trip_end: datetime,
    start: dict[str, float],
    gmaps_client: Any,
    settings: Settings,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    availability: list[dict[str, Any]] = []
    food_stops: list[dict[str, Any]] = []

    for meal in _explicit_meals(state):
        entry, food_stop = _plan_explicit_meal(
            meal=meal,
            segments=segments,
            departure=departure,
            gmaps_client=gmaps_client,
            settings=settings,
        )
        availability.append(entry)
        if food_stop:
            food_stops.append(food_stop)

    if availability:
        return availability, food_stops

    interests = {
        str(interest).strip().lower()
        for interest in state.get("constraints", {}).get("interests", [])
    }
    food_oriented_stops = [stop for stop in stops if _destination_is_food_oriented(stop["destination"])]
    if "food" in interests and food_oriented_stops:
        stop = food_oriented_stops[0]
        availability.append(
            _availability_entry(
                meal="general",
                need="interest",
                status="eat_at_destination",
                time_value=stop["arrive"],
                coords=stop["coords"],
                notes=(
                    f"{stop['destination'].get('name', 'A stop')} is food-oriented, "
                    "so food is already part of this trip."
                ),
            )
        )
        return availability, food_stops

    dinner_time = _meal_time("dinner", departure)
    if departure <= dinner_time <= trip_end and return_arrival <= dinner_time + timedelta(minutes=30):
        availability.append(
            _availability_entry(
                meal="dinner",
                need="optional",
                status="eat_at_home",
                time_value=return_arrival,
                coords=start,
                notes=(
                    f"You are expected back around {_format_time(return_arrival)}, "
                    "so dinner can be at home; no separate restaurant stop is needed."
                ),
            )
        )

    breakfast_time = _meal_time("breakfast", departure)
    remote_stops = [stop for stop in stops if _destination_is_remote(stop["destination"])]
    first_stop = stops[0] if stops else None
    morning_is_long = bool(
        first_stop and (first_stop["arrive"] - departure).total_seconds() > FOOD_STOP_THRESHOLD_SECONDS
    )
    if departure.hour <= 7 and remote_stops and morning_is_long:
        _, search_center, _ = _locate_meal(segments, breakfast_time)
        recommendations = _search_food_near(
            center=search_center,
            stop_start=breakfast_time,
            duration_seconds=FOOD_STOP_DURATION_SECONDS,
            gmaps_client=gmaps_client,
            settings=settings,
        )
        if recommendations:
            names = _food_names(recommendations)
            notes = f"Remote morning route: pick up breakfast near the route. Google Maps options: {names}."
            availability.append(
                _availability_entry(
                    meal="breakfast",
                    need="availability",
                    status="route_options",
                    time_value=breakfast_time,
                    coords=search_center,
                    notes=notes,
                    recommended_places=recommendations,
                )
            )
            food_stops.append(
                _route_food_stop(
                    meal="breakfast",
                    need="availability",
                    status="route_options",
                    stop_start=breakfast_time,
                    duration_seconds=FOOD_STOP_DURATION_SECONDS,
                    coords=search_center,
                    notes=notes,
                    recommended_places=recommendations,
                )
            )
        else:
            availability.append(
                _availability_entry(
                    meal="breakfast",
                    need="availability",
                    status="carry_or_parcel",
                    time_value=departure,
                    coords=start,
                    notes=(
                        "The destination looks remote and food availability could not be confirmed. "
                        "Have breakfast before leaving, carry water/snacks, or take parcel from the start area."
                    ),
                )
            )

    return availability, food_stops


def build_route(
    state: TripState,
    *,
    settings: Settings = SETTINGS,
    gmaps_client: Any = gmaps,
    trip_start: datetime | None = None,
    model: Any | None = None,
) -> dict[str, Any]:
    """Read `selected_destinations` (1-3 stops) and trip constraints, then write the chained round-trip `route`, per-segment `food_stops`, `food_availability`, and a single ordered `timeline` across all stops."""
    selected = [dict(destination) for destination in state.get("selected_destinations", [])]
    if not selected:
        return {"route": {}, "food_stops": [], "food_availability": [], "timeline": []}

    constraints = state["constraints"]
    start = state["isochrone_polygon"]["properties"]["center"]
    start_label = str(constraints.get("start_location") or "Start")
    duration_hours = float(constraints["duration_hours"])
    travel_mode = _travel_mode(str(constraints.get("vehicle", "none")))
    departure = trip_start or trip_start_from_constraints(constraints)

    route_result = gmaps_client.compute_route(
        origin=start,
        destination=start,
        settings=settings,
        travel_mode=travel_mode,
        intermediates=[destination["coords"] for destination in selected],
    )
    legs = list(route_result.get("normalized_legs") or [])
    total_travel_seconds = sum(int(leg.get("duration_seconds", 0)) for leg in legs)
    trip_end = departure + timedelta(hours=duration_hours)

    chat_model = model or get_chat_model(
        model=REASONING_GEMINI_MODEL,
        temperature=1.0,
        response_mime_type="application/json",
    )
    dwell_times = _llm_dwell_times(
        destinations=selected,
        constraints=constraints,
        duration_hours=duration_hours,
        total_travel_seconds=total_travel_seconds,
        model=chat_model,
    )

    stops: list[dict[str, Any]] = []
    current = departure
    for index, destination in enumerate(selected):
        leg = legs[index] if index < len(legs) else {}
        arrive = current + timedelta(seconds=int(leg.get("duration_seconds", 0)))
        dwell_seconds, reason = dwell_times[index]
        depart = arrive + timedelta(seconds=dwell_seconds)
        stops.append(
            {
                "index": index,
                "destination": destination,
                "coords": destination["coords"],
                "label": str(destination.get("name") or f"Stop {index + 1}"),
                "arrive": arrive,
                "depart": depart,
                "dwell_seconds": dwell_seconds,
                "reason": reason,
            }
        )
        current = depart

    final_leg_seconds = int(legs[-1].get("duration_seconds", 0)) if legs else 0
    return_arrival = current + timedelta(seconds=final_leg_seconds)

    segments = _build_segments(
        start=start,
        stops=stops,
        legs=legs,
        departure=departure,
        return_arrival=return_arrival,
    )
    food_availability, food_stops = _plan_food_availability(
        state=state,
        stops=stops,
        segments=segments,
        departure=departure,
        return_arrival=return_arrival,
        trip_end=trip_end,
        start=start,
        gmaps_client=gmaps_client,
        settings=settings,
    )

    timeline: list[dict[str, Any]] = [
        _timeline_entry(
            time_value=departure,
            label=f"Depart {start_label}",
            coords=start,
            entry_type="start",
            notes="Start the trip.",
        )
    ]
    food_notes_by_coords = {
        (round(entry["coords"].get("lat", 0), 4), round(entry["coords"].get("lng", 0), 4)): entry["notes"]
        for entry in food_availability
        if entry.get("status") == "eat_at_destination" and isinstance(entry.get("coords"), dict)
    }
    for stop in stops:
        notes = f"Stop {stop['index'] + 1}. Spend {_format_duration(stop['dwell_seconds'])} here."
        if stop["reason"]:
            notes = f"{notes} {stop['reason']}"
        coord_key = (round(stop["coords"].get("lat", 0), 4), round(stop["coords"].get("lng", 0), 4))
        if coord_key in food_notes_by_coords:
            notes = f"{notes} {food_notes_by_coords[coord_key]}"
        timeline.append(
            _timeline_entry(
                time_value=stop["arrive"],
                label=f"Stop {stop['index'] + 1}: {stop['label']}",
                coords=stop["coords"],
                entry_type="destination",
                notes=notes,
            )
        )
        timeline.append(
            _timeline_entry(
                time_value=stop["depart"],
                label=f"Leave {stop['label']}",
                coords=stop["coords"],
                entry_type="departure",
                notes="Continue the journey.",
            )
        )
    for food_stop in food_stops:
        timeline.append(
            _timeline_entry(
                time_value=datetime.combine(
                    departure.date(),
                    datetime.strptime(food_stop["stop_start"], "%H:%M").time(),
                ),
                label=food_stop["name"],
                coords=food_stop["coords"],
                entry_type="food",
                notes=food_stop["notes"],
            )
        )
    timeline.append(
        _timeline_entry(
            time_value=return_arrival,
            label=f"Back at {start_label}",
            coords=start,
            entry_type="return",
            notes="Trip ends.",
        )
    )
    timeline.sort(key=lambda entry: entry["time"])

    waypoints: list[dict[str, Any]] = [
        {
            "label": start_label,
            "coords": start,
            "type": "start",
            "eta": _format_time(departure),
        }
    ]
    for stop in stops:
        waypoints.append(
            {
                "label": f"Stop {stop['index'] + 1}: {stop['label']}",
                "coords": stop["coords"],
                "type": "destination",
                "eta": _format_time(stop["arrive"]),
                "notes": stop["destination"].get("description", ""),
            }
        )
    for food_stop in food_stops:
        waypoints.append(
            {
                "label": food_stop["name"],
                "coords": food_stop["coords"],
                "type": "food",
                "eta": food_stop["stop_start"],
                "notes": food_stop["notes"],
            }
        )
    waypoints.append(
        {
            "label": start_label,
            "coords": start,
            "type": "return",
            "eta": _format_time(return_arrival),
        }
    )

    coordinates = _decode_polyline(route_result.get("encoded_polyline", ""))
    if not coordinates:
        coordinates = [
            _line_coords(start),
            *[_line_coords(stop["coords"]) for stop in stops],
            _line_coords(start),
        ]

    total_distance_meters = int(route_result.get("distance_meters", 0)) or sum(
        int(leg.get("distance_meters", 0)) for leg in legs
    )

    route_legs: list[dict[str, Any]] = []
    leg_points = [start_label, *[f"Stop {stop['index'] + 1}: {stop['label']}" for stop in stops], start_label]
    leg_departs = [departure, *[stop["depart"] for stop in stops]]
    leg_arrives = [*[stop["arrive"] for stop in stops], return_arrival]
    for index, leg in enumerate(legs):
        route_legs.append(
            {
                "type": "outbound" if index == 0 else ("return" if index == len(legs) - 1 else "between"),
                "from": leg_points[index] if index < len(leg_points) else start_label,
                "to": leg_points[index + 1] if index + 1 < len(leg_points) else start_label,
                "distance_meters": int(leg.get("distance_meters", 0)),
                "duration_seconds": int(leg.get("duration_seconds", 0)),
                "depart_time": _format_time(leg_departs[index]) if index < len(leg_departs) else "",
                "arrive_time": _format_time(leg_arrives[index]) if index < len(leg_arrives) else "",
            }
        )

    route = {
        "geojson": {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates,
            },
            "properties": {
                "type": "route",
                "distance_meters": total_distance_meters,
                "travel_duration_seconds": total_travel_seconds,
            },
        },
        "waypoints": waypoints,
        "legs": route_legs,
        "encoded_polyline": route_result.get("encoded_polyline", ""),
        "total_distance_meters": total_distance_meters,
        "travel_duration_seconds": total_travel_seconds,
        "planned_duration_seconds": int((return_arrival - departure).total_seconds()),
        "raw": route_result.get("raw", {}),
    }

    return {
        "route": route,
        "food_stops": food_stops,
        "food_availability": food_availability,
        "timeline": timeline,
    }
