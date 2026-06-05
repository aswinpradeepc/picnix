from datetime import datetime

from graph.nodes.n4_route import build_route


class FakeGMaps:
    def __init__(
        self,
        *,
        outbound_seconds: int = 3600,
        return_seconds: int = 3600,
        food_results: list[dict] | None = None,
    ) -> None:
        self.routes = [
            {
                "distance_meters": 40_000,
                "duration_seconds": outbound_seconds,
                "encoded_polyline": "encoded-outbound",
                "legs": [{"duration": f"{outbound_seconds}s"}],
            },
            {
                "distance_meters": 42_000,
                "duration_seconds": return_seconds,
                "encoded_polyline": "encoded-return",
                "legs": [{"duration": f"{return_seconds}s"}],
            },
        ]
        self.route_calls = []
        self.food_results = food_results or []
        self.food_search_calls = []
        self.detail_calls = []
        self.validation_windows = []

    def compute_route(self, *, origin, destination, settings=None, travel_mode="DRIVE"):
        self.route_calls.append(
            {
                "origin": origin,
                "destination": destination,
                "travel_mode": travel_mode,
            }
        )
        return self.routes[len(self.route_calls) - 1]

    def search_food_stops_along_route(
        self,
        *,
        route_polyline,
        settings=None,
        max_results=1,
    ):
        self.food_search_calls.append(
            {"route_polyline": route_polyline, "max_results": max_results}
        )
        return self.food_results

    def get_place_details(self, place_id, *, settings=None):
        self.detail_calls.append(place_id)
        return {
            "place_id": place_id,
            "name": "Good Cafe",
            "business_status": "OPERATIONAL",
            "regular_opening_hours": {},
        }

    def validate_place_open_for_window(self, details, window_start, window_end):
        self.validation_windows.append((window_start, window_end))
        return details.get("business_status") == "OPERATIONAL"


def base_state(*, vehicle: str = "car", duration_hours: float = 6) -> dict:
    return {
        "constraints": {
            "start_location": "Kochi",
            "departure_time": "07:00",
            "duration_hours": duration_hours,
            "vehicle": vehicle,
        },
        "isochrone_polygon": {
            "properties": {"center": {"lat": 9.9312, "lng": 76.2673}}
        },
        "validated_destination": {
            "place_id": "dest-1",
            "name": "Athirappilly Falls",
            "coords": {"lat": 10.2859, "lng": 76.5696},
            "description": "Waterfall destination.",
            "notes": [],
        },
        "food_stops": [],
        "route": {},
        "timeline": [],
    }


def test_build_route_creates_round_trip_route_and_timeline_without_food_stop() -> None:
    fake_gmaps = FakeGMaps(outbound_seconds=3600, return_seconds=4200)

    result = build_route(
        base_state(duration_hours=6),
        gmaps_client=fake_gmaps,
        trip_start=datetime(2026, 5, 31, 7, 0),
    )

    assert fake_gmaps.route_calls == [
        {
            "origin": {"lat": 9.9312, "lng": 76.2673},
            "destination": {"lat": 10.2859, "lng": 76.5696},
            "travel_mode": "DRIVE",
        },
        {
            "origin": {"lat": 10.2859, "lng": 76.5696},
            "destination": {"lat": 9.9312, "lng": 76.2673},
            "travel_mode": "DRIVE",
        },
    ]
    assert fake_gmaps.food_search_calls == []
    assert result["food_stops"] == []
    assert result["route"]["total_distance_meters"] == 82_000
    assert result["route"]["travel_duration_seconds"] == 7800
    assert result["route"]["planned_duration_seconds"] == 21_600
    assert result["route"]["geojson"]["geometry"] == {
        "type": "LineString",
        "coordinates": [
            [76.2673, 9.9312],
            [76.5696, 10.2859],
            [76.2673, 9.9312],
        ],
    }
    assert [entry["time"] for entry in result["timeline"]] == [
        "07:00",
        "08:00",
        "11:50",
        "13:00",
    ]
    assert [entry["type"] for entry in result["timeline"]] == [
        "start",
        "destination",
        "return_departure",
        "return",
    ]


def test_build_route_adds_validated_food_stop_for_long_outbound_travel() -> None:
    fake_gmaps = FakeGMaps(
        outbound_seconds=7200,
        return_seconds=7200,
        food_results=[
            {
                "place_id": "low-rating",
                "name": "Okay Tea Shop",
                "coords": {"lat": 9.95, "lng": 76.3},
                "rating": 3.9,
                "types": ["restaurant"],
            },
            {
                "place_id": "food-1",
                "name": "Good Cafe",
                "coords": {"lat": 10.0, "lng": 76.35},
                "rating": 4.5,
                "types": ["cafe"],
                "primary_type": "cafe",
            },
        ],
    )

    result = build_route(
        base_state(duration_hours=8),
        gmaps_client=fake_gmaps,
        trip_start=datetime(2026, 5, 31, 7, 0),
    )

    assert fake_gmaps.food_search_calls == [
        {"route_polyline": "encoded-outbound", "max_results": 5}
    ]
    assert fake_gmaps.detail_calls == ["food-1"]
    assert fake_gmaps.validation_windows == [
        (datetime(2026, 5, 31, 8, 0), datetime(2026, 5, 31, 8, 45))
    ]
    assert result["food_stops"][0]["place_id"] == "food-1"
    assert result["food_stops"][0]["stop_start"] == "08:00"
    assert result["food_stops"][0]["stop_end"] == "08:45"
    assert [entry["type"] for entry in result["timeline"]] == [
        "start",
        "food",
        "destination",
        "return_departure",
        "return",
    ]
    assert [entry["time"] for entry in result["timeline"]] == [
        "07:00",
        "08:00",
        "09:45",
        "13:00",
        "15:00",
    ]
    assert result["route"]["waypoints"][1]["type"] == "food"
    assert result["route"]["planned_duration_seconds"] == 28_800


def test_build_route_uses_departure_time_from_constraints() -> None:
    fake_gmaps = FakeGMaps(outbound_seconds=3600, return_seconds=3600)
    state = base_state(duration_hours=6)
    state["constraints"]["departure_time"] = "09:30"

    result = build_route(state, gmaps_client=fake_gmaps)

    assert [entry["time"] for entry in result["timeline"]] == [
        "09:30",
        "10:30",
        "14:30",
        "15:30",
    ]


def test_build_route_uses_two_wheeler_mode_for_bike_trips() -> None:
    fake_gmaps = FakeGMaps()

    build_route(
        base_state(vehicle="bike"),
        gmaps_client=fake_gmaps,
        trip_start=datetime(2026, 5, 31, 7, 0),
    )

    assert [call["travel_mode"] for call in fake_gmaps.route_calls] == [
        "TWO_WHEELER",
        "TWO_WHEELER",
    ]
