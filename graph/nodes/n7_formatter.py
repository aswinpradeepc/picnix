from __future__ import annotations

from typing import Any

from graph.state import TripState


def _route_feature(route: dict[str, Any]) -> dict[str, Any] | None:
    feature = route.get("geojson", {})
    geometry = feature.get("geometry", {})
    coordinates = geometry.get("coordinates")
    if geometry.get("type") != "LineString" or not isinstance(coordinates, list):
        return None
    if len(coordinates) < 2:
        return None

    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": coordinates,
        },
        "properties": {
            **dict(feature.get("properties", {})),
            "type": "route",
        },
    }


def _point_coordinates(coords: Any) -> list[float] | None:
    if not isinstance(coords, dict):
        return None
    try:
        lat = float(coords["lat"])
        lng = float(coords["lng"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return [lng, lat]


def _waypoint_feature(entry: dict[str, Any]) -> dict[str, Any] | None:
    coordinates = _point_coordinates(entry.get("coords"))
    if not coordinates:
        return None

    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": coordinates,
        },
        "properties": {
            "type": "waypoint",
            "stop_type": str(entry.get("type", "")),
            "label": str(entry.get("label", "")),
            "time": str(entry.get("time", "")),
            "notes": str(entry.get("notes", "")),
        },
    }


def format_final_output(state: TripState) -> dict[str, Any]:
    """Read verified `route`, `timeline`, and `itinerary_draft`, then write `final_geojson` and `final_itinerary` for the UI."""
    features: list[dict[str, Any]] = []

    route_feature = _route_feature(dict(state.get("route", {})))
    if route_feature:
        features.append(route_feature)

    for entry in state.get("timeline", []):
        if not isinstance(entry, dict):
            continue
        waypoint = _waypoint_feature(entry)
        if waypoint:
            features.append(waypoint)

    return {
        "final_geojson": {
            "type": "FeatureCollection",
            "features": features,
        },
        "final_itinerary": str(state.get("itinerary_draft", "")),
    }
