from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any

from config.settings import SETTINGS, Settings
from graph.state import TripState
from tools import gmaps


VALID_NEARBY_SEARCH_TYPES = {
    "art_gallery",
    "beach",
    "cafe",
    "campground",
    "church",
    "cultural_landmark",
    "hiking_area",
    "historical_place",
    "hindu_temple",
    "meal_takeaway",
    "mosque",
    "movie_theater",
    "museum",
    "nature_preserve",
    "observation_deck",
    "park",
    "restaurant",
    "scenic_spot",
    "shopping_mall",
    "store",
    "tourist_attraction",
}

INTEREST_TYPE_MAP = {
    "nature": [
        "park",
        "tourist_attraction",
        "campground",
        "hiking_area",
        "nature_preserve",
        "scenic_spot",
    ],
    "long_rides": ["tourist_attraction", "scenic_spot", "observation_deck"],
    "food": ["restaurant", "cafe", "meal_takeaway"],
    "beach": ["beach", "tourist_attraction"],
    "waterfall": ["tourist_attraction", "park", "hiking_area"],
    "hills": ["hiking_area", "park", "tourist_attraction"],
    "culture": [
        "museum",
        "art_gallery",
        "cultural_landmark",
        "historical_place",
        "hindu_temple",
        "church",
        "mosque",
    ],
    "shopping": ["shopping_mall", "store"],
    "movies": ["movie_theater"],
}

VEHICLE_SPEED_KMH = {
    "bike": 45,
    "car": 65,
    "public": 30,
    "none": 30,
}

EARTH_RADIUS_KM = 6371.0088


def route_trip_type(state: TripState) -> str:
    hours = state["constraints"]["duration_hours"]
    if hours <= 14:
        return "n2_isochrone"
    return "future_multiday"


def _max_one_way_hours(duration_hours: float) -> float:
    return max((duration_hours - 2) / 2, 0.5)


def _radius_km(duration_hours: float, vehicle: str) -> float:
    speed = VEHICLE_SPEED_KMH.get(vehicle, VEHICLE_SPEED_KMH["none"])
    return round(_max_one_way_hours(duration_hours) * speed, 2)


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


def _interest_types(interests: list[str]) -> list[list[str]]:
    selected = interests or ["nature"]
    mapped: list[list[str]] = []
    for interest in selected:
        types = INTEREST_TYPE_MAP.get(str(interest).strip().lower())
        if types and types not in mapped:
            mapped.append(types)
    return mapped or [INTEREST_TYPE_MAP["nature"]]


def _relevance_score(candidate: dict[str, Any], interests: list[str]) -> float:
    haystack = " ".join(
        [
            candidate.get("name", ""),
            candidate.get("description", ""),
            " ".join(candidate.get("types", [])),
        ]
    ).lower()
    candidate_types = set(candidate.get("types", []))
    score = 0
    for interest in interests:
        normalized = str(interest).strip().lower()
        mapped_types = set(INTEREST_TYPE_MAP.get(normalized, []))
        if normalized in haystack or candidate_types.intersection(mapped_types):
            score += 1
    return score


def _score_candidate(
    candidate: dict[str, Any],
    *,
    interests: list[str],
    distance_km: float,
    radius_km: float,
) -> float:
    rating = float(candidate.get("rating") or 0)
    distance_fit = 1 - min(abs((distance_km / radius_km) - 0.65), 1) if radius_km else 0
    relevance = _relevance_score(candidate, interests)
    return round(relevance * 10 + rating * 3 + distance_fit * 2, 3)


def fetch_isochrone_candidates(
    state: TripState,
    *,
    settings: Settings = SETTINGS,
    gmaps_client: Any = gmaps,
) -> dict[str, Any]:
    """Read trip constraints, geocode the start, build a reachable polygon, and write ranked destination candidates."""
    constraints = state["constraints"]
    start_location = constraints["start_location"]
    duration_hours = float(constraints["duration_hours"])
    vehicle = constraints.get("vehicle", "none")
    interests = list(constraints.get("interests", []))

    start = gmaps_client.geocode_location(start_location, settings=settings)
    center = {"lat": start["lat"], "lng": start["lng"]}
    radius = _radius_km(duration_hours, vehicle)
    polygon = gmaps_client.build_reachable_area_polygon(center, radius)

    candidates_by_id: dict[str, dict[str, Any]] = {}
    for included_types in _interest_types(interests):
        for candidate in gmaps_client.search_destinations_nearby(
            center=center,
            radius_km=radius,
            included_types=included_types,
            settings=settings,
            max_results=5,
        ):
            place_id = candidate.get("place_id")
            if not place_id or place_id in candidates_by_id:
                continue
            distance = _distance_km(center, candidate["coords"])
            enriched = {
                **candidate,
                "distance_km": round(distance, 2),
                "score": _score_candidate(
                    candidate,
                    interests=interests,
                    distance_km=distance,
                    radius_km=radius,
                ),
            }
            candidates_by_id[place_id] = enriched

    ranked = sorted(
        candidates_by_id.values(),
        key=lambda candidate: candidate["score"],
        reverse=True,
    )[:5]

    return {
        "isochrone_polygon": polygon,
        "candidates": ranked,
        "candidate_index": 0,
    }
