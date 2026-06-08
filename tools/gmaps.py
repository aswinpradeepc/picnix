from __future__ import annotations

from datetime import datetime, time
from math import asin, atan2, cos, degrees, radians, sin
from typing import Any

import requests

from config.settings import SETTINGS, Settings


GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
EARTH_RADIUS_KM = 6371.0088
PLACES_NEARBY_MAX_RADIUS_METERS = 50_000

PLACE_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.rating",
        "places.types",
        "places.primaryType",
        "places.googleMapsUri",
        "places.editorialSummary",
    ]
)

PLACE_DETAILS_FIELD_MASK = ",".join(
    [
        "id",
        "displayName",
        "formattedAddress",
        "location",
        "rating",
        "types",
        "primaryType",
        "googleMapsUri",
        "editorialSummary",
        "businessStatus",
        "regularOpeningHours",
        "currentOpeningHours",
        "accessibilityOptions",
    ]
)

ROUTES_FIELD_MASK = ",".join(
    [
        "routes.duration",
        "routes.distanceMeters",
        "routes.polyline.encodedPolyline",
        "routes.legs",
    ]
)


class GoogleMapsError(RuntimeError):
    pass


def maps_request(
    method: str,
    url: str,
    *,
    settings: Settings = SETTINGS,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    field_mask: str | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    if not settings.google_maps_api_key:
        raise GoogleMapsError("GOOGLE_MAPS_API_KEY is required for Google Maps calls.")

    request_headers = dict(headers or {})
    if field_mask:
        request_headers["X-Goog-FieldMask"] = field_mask
    if "places.googleapis.com" in url or "routes.googleapis.com" in url:
        request_headers["X-Goog-Api-Key"] = settings.google_maps_api_key

    request_params = dict(params or {})
    if "maps.googleapis.com/maps/api/geocode" in url:
        request_params["key"] = settings.google_maps_api_key

    try:
        response = requests.request(
            method,
            url,
            params=request_params or None,
            headers=request_headers or None,
            json=json_body,
            timeout=timeout,
        )
    except Exception as exc:
        raise GoogleMapsError(f"Google Maps request failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if isinstance(payload, dict) and "error" in payload:
        message = payload["error"].get("message", "unknown Google Maps API error")
        raise GoogleMapsError(message)

    try:
        response.raise_for_status()
    except Exception as exc:
        raise GoogleMapsError(f"Google Maps request failed: {exc}") from exc

    return payload


def _display_name(place: dict[str, Any]) -> str:
    value = place.get("displayName", {})
    if isinstance(value, dict):
        return value.get("text", "")
    return value or ""


def _coords_from_place(place: dict[str, Any]) -> dict[str, float]:
    location = place.get("location", {})
    return {
        "lat": float(location.get("latitude", 0)),
        "lng": float(location.get("longitude", 0)),
    }


def _summary(place: dict[str, Any]) -> str:
    value = place.get("editorialSummary", {})
    if isinstance(value, dict):
        return value.get("text", "")
    return value or ""


def _normalize_place(place: dict[str, Any]) -> dict[str, Any]:
    return {
        "place_id": place.get("id", ""),
        "name": _display_name(place),
        "address": place.get("formattedAddress", ""),
        "coords": _coords_from_place(place),
        "rating": place.get("rating"),
        "types": place.get("types", []),
        "primary_type": place.get("primaryType", ""),
        "google_maps_uri": place.get("googleMapsUri", ""),
        "description": _summary(place),
        "raw": place,
    }


def _duration_to_seconds(duration: str | None) -> int:
    if not duration:
        return 0
    if duration.endswith("s"):
        return int(float(duration[:-1]))
    return int(float(duration))


def geocode_location(address: str, *, settings: Settings = SETTINGS) -> dict[str, Any]:
    payload = maps_request(
        "GET",
        GEOCODING_URL,
        params={"address": address},
        settings=settings,
    )

    status = payload.get("status")
    if status != "OK":
        raise GoogleMapsError(f"Geocoding failed for {address!r}: {status}")
    results = payload.get("results") or []
    if not results:
        raise GoogleMapsError(f"Geocoding returned no results for {address!r}.")

    first = results[0]
    location = first.get("geometry", {}).get("location", {})
    return {
        "formatted_address": first.get("formatted_address", ""),
        "place_id": first.get("place_id", ""),
        "lat": location.get("lat"),
        "lng": location.get("lng"),
        "raw": first,
    }


def build_reachable_area_polygon(
    center: dict[str, float],
    radius_km: float,
    *,
    points: int = 48,
) -> dict[str, Any]:
    lat = radians(center["lat"])
    lng = radians(center["lng"])
    angular_distance = radius_km / EARTH_RADIUS_KM
    coordinates: list[list[float]] = []

    for index in range(points):
        bearing = radians(index * 360 / points)
        point_lat = asin(
            sin(lat) * cos(angular_distance)
            + cos(lat) * sin(angular_distance) * cos(bearing)
        )
        point_lng = lng + atan2(
            sin(bearing) * sin(angular_distance) * cos(lat),
            cos(angular_distance) - sin(lat) * sin(point_lat),
        )
        coordinates.append([degrees(point_lng), degrees(point_lat)])

    coordinates.append(coordinates[0])
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
        "properties": {"radius_km": radius_km, "center": center},
    }


def search_destinations_nearby(
    *,
    center: dict[str, float],
    radius_km: float,
    included_types: list[str],
    settings: Settings = SETTINGS,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    search_radius_meters = min(radius_km * 1000, PLACES_NEARBY_MAX_RADIUS_METERS)
    payload = maps_request(
        "POST",
        PLACES_NEARBY_URL,
        settings=settings,
        field_mask=PLACE_FIELD_MASK,
        json_body={
            "includedTypes": included_types,
            "maxResultCount": max_results,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": center["lat"],
                        "longitude": center["lng"],
                    },
                    "radius": search_radius_meters,
                }
            },
        },
    )
    return [_normalize_place(place) for place in payload.get("places", [])]


def get_place_details(
    place_id: str,
    *,
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    payload = maps_request(
        "GET",
        PLACES_DETAILS_URL.format(place_id=place_id),
        settings=settings,
        field_mask=PLACE_DETAILS_FIELD_MASK,
    )
    details = _normalize_place(payload)
    details["business_status"] = payload.get("businessStatus", "")
    details["regular_opening_hours"] = payload.get("regularOpeningHours", {})
    details["current_opening_hours"] = payload.get("currentOpeningHours", {})
    details["accessibility_options"] = payload.get("accessibilityOptions", {})
    return details


def _waypoint(point: dict[str, float]) -> dict[str, Any]:
    return {
        "location": {
            "latLng": {
                "latitude": point["lat"],
                "longitude": point["lng"],
            }
        }
    }


def _normalize_leg(leg: dict[str, Any]) -> dict[str, Any]:
    duration = leg.get("duration", "")
    return {
        "distance_meters": leg.get("distanceMeters", 0),
        "duration": duration,
        "duration_seconds": _duration_to_seconds(duration),
        "encoded_polyline": leg.get("polyline", {}).get("encodedPolyline", ""),
    }


def compute_route(
    *,
    origin: dict[str, float],
    destination: dict[str, float],
    settings: Settings = SETTINGS,
    travel_mode: str = "DRIVE",
    intermediates: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    json_body: dict[str, Any] = {
        "origin": _waypoint(origin),
        "destination": _waypoint(destination),
        "travelMode": travel_mode,
        "routingPreference": "TRAFFIC_AWARE",
    }
    if intermediates:
        json_body["intermediates"] = [_waypoint(point) for point in intermediates]

    payload = maps_request(
        "POST",
        ROUTES_URL,
        settings=settings,
        field_mask=ROUTES_FIELD_MASK,
        json_body=json_body,
    )

    routes = payload.get("routes") or []
    if not routes:
        raise GoogleMapsError("Routes API returned no routes.")

    route = routes[0]
    duration = route.get("duration", "")
    raw_legs = route.get("legs", [])
    return {
        "distance_meters": route.get("distanceMeters", 0),
        "duration": duration,
        "duration_seconds": _duration_to_seconds(duration),
        "encoded_polyline": route.get("polyline", {}).get("encodedPolyline", ""),
        "legs": raw_legs,
        "normalized_legs": [_normalize_leg(leg) for leg in raw_legs],
        "raw": route,
    }


def search_food_stops_along_route(
    *,
    route_polyline: str,
    settings: Settings = SETTINGS,
    max_results: int = 1,
) -> list[dict[str, Any]]:
    payload = maps_request(
        "POST",
        PLACES_TEXT_SEARCH_URL,
        settings=settings,
        field_mask=PLACE_FIELD_MASK,
        json_body={
            "textQuery": "restaurant cafe",
            "includedType": "restaurant",
            "maxResultCount": max_results,
            "searchAlongRouteParameters": {
                "polyline": {"encodedPolyline": route_polyline},
            },
        },
    )
    return [_normalize_place(place) for place in payload.get("places", [])]


def search_food_spots_near_location(
    *,
    center: dict[str, float],
    settings: Settings = SETTINGS,
    max_results: int = 5,
    radius_meters: int = 5000,
) -> list[dict[str, Any]]:
    json_body: dict[str, Any] = {
        "textQuery": "restaurant cafe",
        "includedType": "restaurant",
        "maxResultCount": max_results,
        "locationBias": {
            "circle": {
                "center": {
                    "latitude": center["lat"],
                    "longitude": center["lng"],
                },
                "radius": radius_meters,
            }
        },
    }

    payload = maps_request(
        "POST",
        PLACES_TEXT_SEARCH_URL,
        settings=settings,
        field_mask=PLACE_FIELD_MASK,
        json_body=json_body,
    )
    return [_normalize_place(place) for place in payload.get("places", [])]


def _google_day(value: datetime) -> int:
    return (value.weekday() + 1) % 7


def _period_time(value: dict[str, Any]) -> time:
    return time(int(value.get("hour", 0)), int(value.get("minute", 0)))


def validate_place_open_for_window(
    details: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
) -> bool:
    if details.get("business_status") == "CLOSED_PERMANENTLY":
        return False

    opening_hours = details.get("regular_opening_hours") or {}
    periods = opening_hours.get("periods") or []
    if not periods:
        return True

    start_day = _google_day(window_start)
    end_day = _google_day(window_end)
    start_time = window_start.time()
    end_time = window_end.time()

    for period in periods:
        open_value = period.get("open", {})
        close_value = period.get("close", {})
        if open_value.get("day") != start_day or close_value.get("day", start_day) != end_day:
            continue
        if _period_time(open_value) <= start_time and end_time <= _period_time(close_value):
            return True

    return False
