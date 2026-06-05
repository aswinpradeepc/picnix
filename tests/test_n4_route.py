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

    def search_food_spots_near_location(
        self,
        *,
        center,
        settings=None,
        max_results=5,
    ):
        self.food_search_calls.append(
            {"center": center, "max_results": max_results}
        )
        return self.food_results

    def get_place_details(self, place_id, *, settings=None):
        self.detail_calls.append(place_id)
        return {
            "place_id": place_id,
            "name": place_id,
            "business_status": "OPERATIONAL",
            "regular_opening_hours": {},
        }

    def validate_place_open_for_window(self, details, window_start, window_end):
        self.validation_windows.append((window_start, window_end))
        return details.get("business_status") == "OPERATIONAL"


def base_state(*, vehicle: str = "car", duration_hours: float = 6) -> dict:
    return {
        "raw_messages": [],
        "constraints": {
            "start_location": "Kochi",
            "departure_time": "07:00",
            "duration_hours": duration_hours,
            "vehicle": vehicle,
            "interests": [],
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
            "types": ["tourist_attraction"],
        },
        "food_stops": [],
        "food_availability": [],
        "route": {},
        "timeline": [],
    }


def food_candidate(place_id: str = "food-1") -> dict:
    return {
        "place_id": place_id,
        "name": "Dinner House",
        "coords": {"lat": 10.1, "lng": 76.42},
        "rating": 4.4,
        "types": ["restaurant"],
        "primary_type": "restaurant",
    }


def test_build_route_creates_round_trip_route_without_food_requirement() -> None:
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
    assert result["food_availability"] == []
    assert result["route"]["total_distance_meters"] == 82_000
    assert result["route"]["travel_duration_seconds"] == 7800
    assert [entry["time"] for entry in result["timeline"]] == [
        "07:00",
        "08:00",
        "10:00",
        "11:10",
    ]


def test_explicit_dinner_uses_dynamic_route_segment_food_search() -> None:
    fake_gmaps = FakeGMaps(
        outbound_seconds=3200,
        return_seconds=3200,
        food_results=[food_candidate("dinner-1")],
    )
    state = base_state(duration_hours=7)
    state["isochrone_polygon"]["properties"]["center"] = {"lat": 10.0467, "lng": 76.3289}
    state["validated_destination"]["name"] = "Malayattoor Kurishumudy International Shrine"
    state["validated_destination"]["coords"] = {"lat": 10.2076, "lng": 76.5086}
    state["constraints"]["departure_time"] = "15:00"
    state["constraints"]["interests"] = ["food", "culture"]
    state["raw_messages"] = [
        {
            "role": "user",
            "content": "Starting at 3 pm and back around 10 pm. Include dinner.",
        }
    ]

    result = build_route(
        state,
        gmaps_client=fake_gmaps,
        trip_start=datetime(2026, 5, 31, 15, 0),
    )

    assert fake_gmaps.food_search_calls == [
        {
            "center": {"lat": 10.09497, "lng": 76.38281},
            "max_results": 5,
        }
    ]
    assert fake_gmaps.validation_windows == [
        (datetime(2026, 5, 31, 18, 46, 40), datetime(2026, 5, 31, 20, 1, 40))
    ]
    assert result["food_availability"][0]["status"] == "route_options"
    assert result["food_availability"][0]["recommended_places"][0]["place_id"] == "dinner-1"
    assert result["food_stops"][0]["name"] == "Dinner options near route"
    assert "Google Maps options: dinner-1." in result["food_stops"][0]["notes"]
    assert [entry["type"] for entry in result["timeline"]] == [
        "start",
        "destination",
        "return_departure",
        "food",
        "return",
    ]


def test_food_oriented_destination_satisfies_explicit_dinner_without_extra_stop() -> None:
    fake_gmaps = FakeGMaps(
        outbound_seconds=1800,
        return_seconds=1800,
        food_results=[food_candidate("unused")],
    )
    state = base_state(duration_hours=5)
    state["validated_destination"] = {
        "place_id": "swargam",
        "name": "Swargam",
        "coords": {"lat": 10.0, "lng": 76.35},
        "description": "Food-oriented destination.",
        "notes": [],
        "types": ["restaurant"],
        "primary_type": "restaurant",
    }
    state["constraints"]["departure_time"] = "17:00"
    state["raw_messages"] = [{"role": "user", "content": "Include dinner at Swargam."}]

    result = build_route(
        state,
        gmaps_client=fake_gmaps,
        trip_start=datetime(2026, 5, 31, 17, 0),
    )

    assert fake_gmaps.food_search_calls == []
    assert result["food_stops"] == []
    assert result["food_availability"] == [
        {
            "meal": "dinner",
            "need": "explicit",
            "status": "eat_at_destination",
            "time": "17:30",
            "coords": {"lat": 10.0, "lng": 76.35},
            "notes": "Swargam is food-oriented, so plan dinner there instead of adding a separate restaurant stop.",
            "recommended_places": [],
        }
    ]
    destination_entry = next(entry for entry in result["timeline"] if entry["type"] == "destination")
    assert "plan dinner there" in destination_entry["notes"]


def test_dinner_window_without_explicit_food_need_can_be_eat_at_home() -> None:
    fake_gmaps = FakeGMaps(outbound_seconds=3200, return_seconds=3200)
    state = base_state(duration_hours=7)
    state["constraints"]["departure_time"] = "15:00"

    result = build_route(
        state,
        gmaps_client=fake_gmaps,
        trip_start=datetime(2026, 5, 31, 15, 0),
    )

    assert fake_gmaps.food_search_calls == []
    assert result["food_stops"] == []
    assert result["food_availability"][0]["status"] == "eat_at_home"
    assert result["food_availability"][0]["meal"] == "dinner"
    assert "dinner can be at home" in result["food_availability"][0]["notes"]


def test_remote_morning_destination_without_food_options_gets_carry_or_parcel_guidance() -> None:
    fake_gmaps = FakeGMaps(outbound_seconds=7200, return_seconds=7200, food_results=[])
    state = base_state(duration_hours=8)
    state["constraints"]["departure_time"] = "06:00"
    state["validated_destination"]["types"] = ["hiking_area"]
    state["validated_destination"]["primary_type"] = "hiking_area"

    result = build_route(
        state,
        gmaps_client=fake_gmaps,
        trip_start=datetime(2026, 5, 31, 6, 0),
    )

    assert fake_gmaps.food_search_calls
    assert result["food_stops"] == []
    assert result["food_availability"][0]["meal"] == "breakfast"
    assert result["food_availability"][0]["status"] == "carry_or_parcel"
    assert "carry water/snacks" in result["food_availability"][0]["notes"]


def test_build_route_uses_departure_time_from_constraints() -> None:
    fake_gmaps = FakeGMaps(outbound_seconds=3600, return_seconds=3600)
    state = base_state(duration_hours=6)
    state["constraints"]["departure_time"] = "09:30"

    result = build_route(state, gmaps_client=fake_gmaps)

    assert [entry["time"] for entry in result["timeline"]] == [
        "09:30",
        "10:30",
        "12:30",
        "13:30",
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
