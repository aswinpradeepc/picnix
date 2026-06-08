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
Always return dwell_minutes as a plain integer with no unit suffix.
"""


def _ceiling_dwell_seconds(
    duration_hours: float,
    total_travel_seconds: int,
    num_destinations: int,
) -> int:
    available = max(int(duration_hours * 3600) - total_travel_seconds, 0)
    return max(MIN_DWELL_SECONDS, available // max(num_destinations, 1))


def _parse_dwell_response(content: Any, place_id: str) -> tuple[int, str]:
    raw = content if isinstance(content, str) else str(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # attempt to extract array from surrounding text
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
        else:
            raise

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise ValueError("Dwell-time response is not a non-empty list.")

    # prefer the entry matching place_id; fall back to first entry
    entry = next(
        (item for item in data if str(item.get("place_id", "")) == place_id),
        data[0],
    )
    dwell_minutes = int(entry.get("dwell_minutes", 0))
    reason = str(entry.get("reason", "")).strip()
    return dwell_minutes * 60, reason


def _llm_dwell_seconds(
    *,
    destination: dict[str, Any],
    constraints: dict[str, Any],
    duration_hours: float,
    num_destinations: int,
    total_travel_seconds: int,
    model: Any,
) -> tuple[int, str]:
    ceiling = _ceiling_dwell_seconds(duration_hours, total_travel_seconds, num_destinations)
    payload = {
        "destinations": [
            {
                "place_id": destination.get("place_id", ""),
                "name": destination.get("name", ""),
                "primary_type": destination.get("primary_type", ""),
                "description": destination.get("description", ""),
            }
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
    response = model.invoke([
        SystemMessage(content=DWELL_TIME_SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(payload, sort_keys=True)),
    ])
    dwell_seconds, reason = _parse_dwell_response(
        response.content, destination.get("place_id", "")
    )
    clamped = max(MIN_DWELL_SECONDS, min(dwell_seconds, ceiling))
    return clamped, reason


def _coords_from_line(value: list[float]) -> dict[str, float]:
    return {"lat": float(value[1]), "lng": float(value[0])}


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


def _leg_points(
    *,
    fallback_start: dict[str, float],
    fallback_end: dict[str, float],
    route: dict[str, Any],
) -> list[list[float]]:
    decoded = _decode_polyline(route.get("encoded_polyline", ""))
    if decoded:
        return decoded
    return [_line_coords(fallback_start), _line_coords(fallback_end)]


def _route_point_for_meal(
    *,
    meal_time: datetime,
    departure: datetime,
    arrival_at_destination: datetime,
    depart_destination: datetime,
    return_arrival: datetime,
    start: dict[str, float],
    destination_coords: dict[str, float],
    outbound: dict[str, Any],
    inbound: dict[str, Any],
) -> tuple[str, dict[str, float], datetime]:
    outbound_points = _leg_points(
        fallback_start=start,
        fallback_end=destination_coords,
        route=outbound,
    )
    inbound_points = _leg_points(
        fallback_start=destination_coords,
        fallback_end=start,
        route=inbound,
    )

    if meal_time <= arrival_at_destination:
        duration = max((arrival_at_destination - departure).total_seconds(), 1)
        fraction = (meal_time - departure).total_seconds() / duration
        return "outbound", _point_on_polyline(outbound_points, fraction), meal_time

    if meal_time <= depart_destination:
        return "destination", destination_coords, meal_time

    if meal_time <= return_arrival:
        duration = max((return_arrival - depart_destination).total_seconds(), 1)
        fraction = (meal_time - depart_destination).total_seconds() / duration
        return "return", _point_on_polyline(inbound_points, fraction), meal_time

    duration = max((return_arrival - depart_destination).total_seconds(), 1)
    near_end_fraction = 0.7 if (meal_time - return_arrival) <= timedelta(minutes=45) else 1.0
    return "return", _point_on_polyline(inbound_points, near_end_fraction), return_arrival


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


def _plan_explicit_meal(
    *,
    meal: str,
    state: TripState,
    destination: dict[str, Any],
    destination_coords: dict[str, float],
    departure: datetime,
    arrival_at_destination: datetime,
    depart_destination: datetime,
    return_arrival: datetime,
    start: dict[str, float],
    outbound: dict[str, Any],
    inbound: dict[str, Any],
    gmaps_client: Any,
    settings: Settings,
) -> tuple[dict[str, Any], dict[str, Any] | None, datetime | None]:
    meal_time = _meal_time(meal, departure)
    duration_seconds = _meal_duration(meal)

    if _destination_is_food_oriented(destination):
        notes = (
            f"{destination.get('name', 'The destination')} is food-oriented, so plan "
            f"{meal} there instead of adding a separate restaurant stop."
        )
        return (
            _availability_entry(
                meal=meal,
                need="explicit",
                status="eat_at_destination",
                time_value=arrival_at_destination,
                coords=destination_coords,
                notes=notes,
            ),
            None,
            None,
        )

    location_type, search_center, stop_start = _route_point_for_meal(
        meal_time=meal_time,
        departure=departure,
        arrival_at_destination=arrival_at_destination,
        depart_destination=depart_destination,
        return_arrival=return_arrival,
        start=start,
        destination_coords=destination_coords,
        outbound=outbound,
        inbound=inbound,
    )
    recommendations = _search_food_near(
        center=search_center,
        stop_start=stop_start,
        duration_seconds=duration_seconds,
        gmaps_client=gmaps_client,
        settings=settings,
    )

    if recommendations:
        names = _food_names(recommendations)
        if location_type == "destination":
            status = "destination_options"
            notes = f"Food is available near the destination for {meal}. Google Maps options: {names}."
        else:
            status = "route_options"
            notes = f"Plan {meal} near this route segment. Google Maps options: {names}."

        availability = _availability_entry(
            meal=meal,
            need="explicit",
            status=status,
            time_value=stop_start,
            coords=search_center,
            notes=notes,
            recommended_places=recommendations,
        )
        food_stop = _route_food_stop(
            meal=meal,
            need="explicit",
            status=status,
            stop_start=stop_start,
            duration_seconds=duration_seconds,
            coords=search_center,
            notes=notes,
            recommended_places=recommendations,
        )
        adjusted_return = None
        if location_type == "return" and stop_start >= return_arrival:
            adjusted_return = stop_start + timedelta(seconds=duration_seconds)
        return availability, food_stop, adjusted_return

    notes = (
        f"Food availability for {meal} could not be confirmed near the destination or route. "
        "Carry water/snacks or pick up parcel before leaving."
    )
    return (
        _availability_entry(
            meal=meal,
            need="explicit",
            status="carry_or_parcel",
            time_value=stop_start,
            coords=search_center,
            notes=notes,
        ),
        None,
        None,
    )


def _plan_food_availability(
    *,
    state: TripState,
    destination: dict[str, Any],
    destination_coords: dict[str, float],
    departure: datetime,
    arrival_at_destination: datetime,
    depart_destination: datetime,
    return_arrival: datetime,
    trip_end: datetime,
    start: dict[str, float],
    outbound: dict[str, Any],
    inbound: dict[str, Any],
    gmaps_client: Any,
    settings: Settings,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], datetime]:
    availability: list[dict[str, Any]] = []
    food_stops: list[dict[str, Any]] = []
    adjusted_return = return_arrival

    for meal in _explicit_meals(state):
        entry, food_stop, new_return = _plan_explicit_meal(
            meal=meal,
            state=state,
            destination=destination,
            destination_coords=destination_coords,
            departure=departure,
            arrival_at_destination=arrival_at_destination,
            depart_destination=depart_destination,
            return_arrival=adjusted_return,
            start=start,
            outbound=outbound,
            inbound=inbound,
            gmaps_client=gmaps_client,
            settings=settings,
        )
        availability.append(entry)
        if food_stop:
            food_stops.append(food_stop)
        if new_return:
            adjusted_return = new_return

    if availability:
        return availability, food_stops, adjusted_return

    interests = {
        str(interest).strip().lower()
        for interest in state.get("constraints", {}).get("interests", [])
    }
    if "food" in interests and _destination_is_food_oriented(destination):
        availability.append(
            _availability_entry(
                meal="general",
                need="interest",
                status="eat_at_destination",
                time_value=arrival_at_destination,
                coords=destination_coords,
                notes=(
                    f"{destination.get('name', 'The destination')} is food-oriented, "
                    "so food is already part of this stop."
                ),
            )
        )
        return availability, food_stops, adjusted_return

    dinner_time = _meal_time("dinner", departure)
    if departure <= dinner_time <= trip_end and adjusted_return <= dinner_time + timedelta(minutes=30):
        availability.append(
            _availability_entry(
                meal="dinner",
                need="optional",
                status="eat_at_home",
                time_value=adjusted_return,
                coords=start,
                notes=(
                    f"You are expected back around {_format_time(adjusted_return)}, "
                    "so dinner can be at home; no separate restaurant stop is needed."
                ),
            )
        )

    breakfast_time = _meal_time("breakfast", departure)
    if (
        departure.hour <= 7
        and (arrival_at_destination - departure).total_seconds() > FOOD_STOP_THRESHOLD_SECONDS
        and _destination_is_remote(destination)
    ):
        search_center = _route_point_for_meal(
            meal_time=breakfast_time,
            departure=departure,
            arrival_at_destination=arrival_at_destination,
            depart_destination=depart_destination,
            return_arrival=adjusted_return,
            start=start,
            destination_coords=destination_coords,
            outbound=outbound,
            inbound=inbound,
        )[1]
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

    return availability, food_stops, adjusted_return


def build_route(
    state: TripState,
    *,
    settings: Settings = SETTINGS,
    gmaps_client: Any = gmaps,
    trip_start: datetime | None = None,
    model: Any | None = None,
) -> dict[str, Any]:
    """Read the confirmed destination and trip constraints, then write the round-trip `route`, validated `food_stops`, `food_availability`, and ordered `timeline`."""
    destination = dict(state.get("validated_destination", {}))
    if not destination:
        return {"route": {}, "food_stops": [], "food_availability": [], "timeline": []}

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
    trip_end = departure + timedelta(hours=duration_hours)

    chat_model = model or get_chat_model(model=REASONING_GEMINI_MODEL, temperature=1.0, response_mime_type="application/json")
    destination_seconds, dwell_reason = _llm_dwell_seconds(
        destination=destination,
        constraints=constraints,
        duration_hours=duration_hours,
        num_destinations=1,
        total_travel_seconds=total_travel_seconds,
        model=chat_model,
    )

    arrival_at_destination = departure + timedelta(seconds=outbound_seconds)
    depart_destination = arrival_at_destination + timedelta(seconds=destination_seconds)
    return_arrival = depart_destination + timedelta(seconds=inbound_seconds)

    food_availability, food_stops, return_arrival = _plan_food_availability(
        state=state,
        destination=destination,
        destination_coords=destination_coords,
        departure=departure,
        arrival_at_destination=arrival_at_destination,
        depart_destination=depart_destination,
        return_arrival=return_arrival,
        trip_end=trip_end,
        start=start,
        outbound=outbound,
        inbound=inbound,
        gmaps_client=gmaps_client,
        settings=settings,
    )

    destination_notes = f"Spend {_format_duration(destination_seconds)} here."
    if dwell_reason:
        destination_notes = f"{destination_notes} {dwell_reason}"
    destination_food_notes = [
        entry["notes"]
        for entry in food_availability
        if entry.get("status") == "eat_at_destination"
    ]
    if destination_food_notes:
        destination_notes = f"{destination_notes} {destination_food_notes[0]}"

    timeline = [
        _timeline_entry(
            time_value=departure,
            label=f"Depart {start_label}",
            coords=start,
            entry_type="start",
            notes="Start the trip.",
        ),
        _timeline_entry(
            time_value=arrival_at_destination,
            label=destination_label,
            coords=destination_coords,
            entry_type="destination",
            notes=destination_notes,
        ),
        _timeline_entry(
            time_value=depart_destination,
            label=f"Leave {destination_label}",
            coords=destination_coords,
            entry_type="return_departure",
            notes="Start the return journey.",
        ),
    ]
    for food_stop in food_stops:
        timeline.append(
            _timeline_entry(
                time_value=datetime.combine(departure.date(), datetime.strptime(food_stop["stop_start"], "%H:%M").time()),
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

    waypoints = [
        {
            "label": start_label,
            "coords": start,
            "type": "start",
            "eta": _format_time(departure),
        },
        {
            "label": destination_label,
            "coords": destination_coords,
            "type": "destination",
            "eta": _format_time(arrival_at_destination),
            "notes": destination.get("description", ""),
        },
        *[
            {
                "label": food_stop["name"],
                "coords": food_stop["coords"],
                "type": "food",
                "eta": food_stop["stop_start"],
                "notes": food_stop["notes"],
            }
            for food_stop in food_stops
        ],
        {
            "label": start_label,
            "coords": start,
            "type": "return",
            "eta": _format_time(return_arrival),
        },
    ]

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
        "food_stops": food_stops,
        "food_availability": food_availability,
        "timeline": timeline,
    }
