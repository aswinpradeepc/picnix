import os
from datetime import datetime

import pytest
import requests

from config.settings import Settings, load_settings, missing_required_keys


def make_settings(
    *,
    google_maps_api_key: str = "gmaps-key",
    mapbox_token: str = "mapbox-token",
    google_cloud_project: str = "picnix-project",
    google_cloud_location: str = "asia-south1",
    google_application_credentials: str = "",
) -> Settings:
    return Settings(
        google_maps_api_key=google_maps_api_key,
        mapbox_token=mapbox_token,
        google_cloud_project=google_cloud_project,
        google_cloud_location=google_cloud_location,
        google_application_credentials=google_application_credentials,
    )


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_mapbox_token_helpers_return_and_require_token() -> None:
    from tools.mapbox import MapboxConfigurationError, get_mapbox_token, require_mapbox_token

    assert get_mapbox_token(make_settings()) == "mapbox-token"
    assert require_mapbox_token(make_settings()) == "mapbox-token"

    with pytest.raises(MapboxConfigurationError, match="MAPBOX_TOKEN"):
        require_mapbox_token(make_settings(mapbox_token=""))


def test_vertex_model_uses_google_genai_with_vertex_backend() -> None:
    from langchain_google_genai import ChatGoogleGenerativeAI

    from tools.vertex import get_chat_model

    model = get_chat_model(settings=make_settings(), temperature=0)

    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model == "gemini-2.5-flash"
    assert model.project == "picnix-project"
    assert model.location == "asia-south1"
    assert model.vertexai is True
    assert model.temperature == 0


def test_geocode_location_normalizes_google_response(monkeypatch) -> None:
    from tools import gmaps

    def fake_request(method, url, **kwargs):
        assert method == "GET"
        assert url.endswith("/maps/api/geocode/json")
        assert kwargs["params"]["address"] == "Kochi, Kerala"
        assert kwargs["params"]["key"] == "gmaps-key"
        return FakeResponse(
            {
                "status": "OK",
                "results": [
                    {
                        "formatted_address": "Kochi, Kerala, India",
                        "place_id": "kochi-place-id",
                        "geometry": {"location": {"lat": 9.9312, "lng": 76.2673}},
                    }
                ],
            }
        )

    monkeypatch.setattr(gmaps.requests, "request", fake_request)

    result = gmaps.geocode_location("Kochi, Kerala", settings=make_settings())

    assert result == {
        "formatted_address": "Kochi, Kerala, India",
        "place_id": "kochi-place-id",
        "lat": 9.9312,
        "lng": 76.2673,
        "raw": {
            "formatted_address": "Kochi, Kerala, India",
            "place_id": "kochi-place-id",
            "geometry": {"location": {"lat": 9.9312, "lng": 76.2673}},
        },
    }


def test_nearby_search_normalizes_candidate_places(monkeypatch) -> None:
    from tools import gmaps

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert url == "https://places.googleapis.com/v1/places:searchNearby"
        assert kwargs["headers"]["X-Goog-Api-Key"] == "gmaps-key"
        assert "places.displayName" in kwargs["headers"]["X-Goog-FieldMask"]
        assert kwargs["json"]["includedTypes"] == ["tourist_attraction"]
        return FakeResponse(
            {
                "places": [
                    {
                        "id": "place-1",
                        "displayName": {"text": "Mattancherry Palace"},
                        "formattedAddress": "Mattancherry, Kochi, Kerala",
                        "location": {"latitude": 9.9576, "longitude": 76.2596},
                        "rating": 4.4,
                        "types": ["tourist_attraction", "museum"],
                        "primaryType": "tourist_attraction",
                        "googleMapsUri": "https://maps.google.com/?cid=1",
                        "editorialSummary": {"text": "Historic palace in Kochi."},
                    }
                ]
            }
        )

    monkeypatch.setattr(gmaps.requests, "request", fake_request)

    results = gmaps.search_destinations_nearby(
        center={"lat": 9.9312, "lng": 76.2673},
        radius_km=5,
        included_types=["tourist_attraction"],
        settings=make_settings(),
    )

    assert results == [
        {
            "place_id": "place-1",
            "name": "Mattancherry Palace",
            "address": "Mattancherry, Kochi, Kerala",
            "coords": {"lat": 9.9576, "lng": 76.2596},
            "rating": 4.4,
            "types": ["tourist_attraction", "museum"],
            "primary_type": "tourist_attraction",
            "google_maps_uri": "https://maps.google.com/?cid=1",
            "description": "Historic palace in Kochi.",
            "raw": {
                "id": "place-1",
                "displayName": {"text": "Mattancherry Palace"},
                "formattedAddress": "Mattancherry, Kochi, Kerala",
                "location": {"latitude": 9.9576, "longitude": 76.2596},
                "rating": 4.4,
                "types": ["tourist_attraction", "museum"],
                "primaryType": "tourist_attraction",
                "googleMapsUri": "https://maps.google.com/?cid=1",
                "editorialSummary": {"text": "Historic palace in Kochi."},
            },
        }
    ]


def test_place_details_normalizes_opening_hours(monkeypatch) -> None:
    from tools import gmaps

    def fake_request(method, url, **kwargs):
        assert method == "GET"
        assert url == "https://places.googleapis.com/v1/places/place-1"
        assert kwargs["headers"]["X-Goog-Api-Key"] == "gmaps-key"
        return FakeResponse(
            {
                "id": "place-1",
                "displayName": {"text": "Mattancherry Palace"},
                "businessStatus": "OPERATIONAL",
                "regularOpeningHours": {
                    "periods": [
                        {
                            "open": {"day": 0, "hour": 9, "minute": 0},
                            "close": {"day": 0, "hour": 17, "minute": 0},
                        }
                    ]
                },
                "location": {"latitude": 9.9576, "longitude": 76.2596},
            }
        )

    monkeypatch.setattr(gmaps.requests, "request", fake_request)

    details = gmaps.get_place_details("place-1", settings=make_settings())

    assert details["place_id"] == "place-1"
    assert details["name"] == "Mattancherry Palace"
    assert details["business_status"] == "OPERATIONAL"
    assert details["regular_opening_hours"]["periods"][0]["open"]["day"] == 0


def test_compute_route_normalizes_routes_response(monkeypatch) -> None:
    from tools import gmaps

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert url == "https://routes.googleapis.com/directions/v2:computeRoutes"
        assert kwargs["headers"]["X-Goog-Api-Key"] == "gmaps-key"
        assert kwargs["json"]["travelMode"] == "DRIVE"
        return FakeResponse(
            {
                "routes": [
                    {
                        "distanceMeters": 17047,
                        "duration": "1869s",
                        "polyline": {"encodedPolyline": "encoded-route"},
                        "legs": [{"distanceMeters": 17047, "duration": "1869s"}],
                    }
                ]
            }
        )

    monkeypatch.setattr(gmaps.requests, "request", fake_request)

    route = gmaps.compute_route(
        origin={"lat": 9.9312, "lng": 76.2673},
        destination={"lat": 10.0261, "lng": 76.3125},
        settings=make_settings(),
    )

    assert route == {
        "distance_meters": 17047,
        "duration": "1869s",
        "duration_seconds": 1869,
        "encoded_polyline": "encoded-route",
        "legs": [{"distanceMeters": 17047, "duration": "1869s"}],
        "raw": {
            "distanceMeters": 17047,
            "duration": "1869s",
            "polyline": {"encodedPolyline": "encoded-route"},
            "legs": [{"distanceMeters": 17047, "duration": "1869s"}],
        },
    }


def test_food_stop_search_uses_search_along_route_parameters(monkeypatch) -> None:
    from tools import gmaps

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert url == "https://places.googleapis.com/v1/places:searchText"
        assert kwargs["json"]["textQuery"] == "restaurant cafe"
        assert kwargs["json"]["searchAlongRouteParameters"] == {
            "polyline": {"encodedPolyline": "encoded-route"}
        }
        return FakeResponse(
            {
                "places": [
                    {
                        "id": "food-1",
                        "displayName": {"text": "Good Cafe"},
                        "formattedAddress": "Kochi, Kerala",
                        "location": {"latitude": 9.95, "longitude": 76.26},
                        "rating": 4.5,
                        "types": ["restaurant", "cafe"],
                        "primaryType": "restaurant",
                    }
                ]
            }
        )

    monkeypatch.setattr(gmaps.requests, "request", fake_request)

    results = gmaps.search_food_stops_along_route(
        route_polyline="encoded-route",
        settings=make_settings(),
    )

    assert results[0]["place_id"] == "food-1"
    assert results[0]["name"] == "Good Cafe"


def test_reachable_area_polygon_is_closed_geojson_polygon() -> None:
    from tools.gmaps import build_reachable_area_polygon

    polygon = build_reachable_area_polygon({"lat": 9.9312, "lng": 76.2673}, 10, points=12)

    assert polygon["type"] == "Feature"
    assert polygon["geometry"]["type"] == "Polygon"
    coordinates = polygon["geometry"]["coordinates"][0]
    assert len(coordinates) == 13
    assert coordinates[0] == coordinates[-1]
    assert polygon["properties"]["radius_km"] == 10


def test_validate_place_open_for_window_uses_google_periods() -> None:
    from tools.gmaps import validate_place_open_for_window

    details = {
        "business_status": "OPERATIONAL",
        "regular_opening_hours": {
            "periods": [
                {
                    "open": {"day": 0, "hour": 9, "minute": 0},
                    "close": {"day": 0, "hour": 17, "minute": 0},
                }
            ]
        },
    }

    assert validate_place_open_for_window(
        details,
        datetime(2026, 5, 31, 10, 0),
        datetime(2026, 5, 31, 12, 0),
    ) is True
    assert validate_place_open_for_window(
        details,
        datetime(2026, 5, 31, 18, 0),
        datetime(2026, 5, 31, 19, 0),
    ) is False
    assert validate_place_open_for_window(
        {**details, "business_status": "CLOSED_PERMANENTLY"},
        datetime(2026, 5, 31, 10, 0),
        datetime(2026, 5, 31, 12, 0),
    ) is False


live = pytest.mark.skipif(
    os.getenv("PICNIX_RUN_LIVE_TESTS") != "1",
    reason="set PICNIX_RUN_LIVE_TESTS=1 to run live external-service smoke tests",
)


def require_live_settings() -> Settings:
    settings = load_settings()
    missing = missing_required_keys(settings)
    if missing:
        pytest.skip(f"missing required .env keys: {', '.join(missing)}")
    return settings


@pytest.mark.live
@live
def test_live_geocoding_api_smoke() -> None:
    from tools.gmaps import geocode_location

    result = geocode_location("Kochi, Kerala", settings=require_live_settings())

    assert result["formatted_address"]
    assert abs(result["lat"] - 9.9312) < 1
    assert abs(result["lng"] - 76.2673) < 1


@pytest.mark.live
@live
def test_live_places_api_smoke() -> None:
    from tools.gmaps import search_destinations_nearby

    results = search_destinations_nearby(
        center={"lat": 9.9312, "lng": 76.2673},
        radius_km=5,
        included_types=["tourist_attraction"],
        settings=require_live_settings(),
        max_results=1,
    )

    assert results
    assert results[0]["place_id"]
    assert results[0]["name"]


@pytest.mark.live
@live
def test_live_routes_api_smoke() -> None:
    from tools.gmaps import compute_route

    route = compute_route(
        origin={"lat": 9.9312, "lng": 76.2673},
        destination={"lat": 10.0261, "lng": 76.3125},
        settings=require_live_settings(),
    )

    assert route["distance_meters"] > 0
    assert route["duration_seconds"] > 0


@pytest.mark.live
@live
def test_live_mapbox_token_smoke() -> None:
    from tools.mapbox import require_mapbox_token

    response = requests.get(
        "https://api.mapbox.com/styles/v1/mapbox/streets-v12",
        params={"access_token": require_mapbox_token(require_live_settings())},
        timeout=20,
    )

    response.raise_for_status()
    assert response.json()["name"] == "Mapbox Streets"


@pytest.mark.live
@live
def test_live_vertex_api_smoke() -> None:
    from tools.vertex import get_chat_model

    response = get_chat_model(settings=require_live_settings(), temperature=0).invoke(
        "Reply with exactly: PICNIX_VERTEX_OK"
    )

    assert "PICNIX_VERTEX_OK" in response.content
