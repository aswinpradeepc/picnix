import json
from datetime import datetime

from graph.nodes.n4_route import build_route


class FakeGMaps:
    """A single multi-waypoint compute_route call returning one normalized leg per hop."""

    def __init__(
        self,
        *,
        legs: list[dict] | None = None,
        distance_meters: int = 82_000,
        encoded_polyline: str = "encoded-route",
        food_results: list[dict] | None = None,
    ) -> None:
        self.legs = legs or [
            {"distance_meters": 40_000, "duration_seconds": 3600, "encoded_polyline": "leg-out"},
            {"distance_meters": 42_000, "duration_seconds": 4200, "encoded_polyline": "leg-back"},
        ]
        self.distance_meters = distance_meters
        self.encoded_polyline = encoded_polyline
        self.route_calls: list[dict] = []
        self.food_results = food_results or []
        self.food_search_calls: list[dict] = []
        self.detail_calls: list[str] = []
        self.validation_windows: list[tuple] = []

    def compute_route(
        self,
        *,
        origin,
        destination,
        settings=None,
        travel_mode="DRIVE",
        intermediates=None,
    ):
        self.route_calls.append(
            {
                "origin": origin,
                "destination": destination,
                "travel_mode": travel_mode,
                "intermediates": intermediates,
            }
        )
        return {
            "distance_meters": self.distance_meters,
            "duration": "",
            "duration_seconds": sum(leg["duration_seconds"] for leg in self.legs),
            "encoded_polyline": self.encoded_polyline,
            "legs": [],
            "normalized_legs": self.legs,
            "raw": {},
        }

    def search_food_spots_near_location(self, *, center, settings=None, max_results=5):
        self.food_search_calls.append({"center": center, "max_results": max_results})
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


def destination(place_id: str = "dest-1", **overrides) -> dict:
    base = {
        "place_id": place_id,
        "name": "Athirappilly Falls",
        "coords": {"lat": 10.2859, "lng": 76.5696},
        "description": "Waterfall destination.",
        "notes": [],
        "types": ["tourist_attraction"],
    }
    base.update(overrides)
    return base


def base_state(
    *,
    vehicle: str = "car",
    duration_hours: float = 6,
    selected: list[dict] | None = None,
) -> dict:
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
        "selected_destinations": selected or [destination()],
        "food_stops": [],
        "food_availability": [],
        "route": {},
        "timeline": [],
    }


class FakeLLM:
    """Returns a fixed dwell value for every destination in the payload, so N4 tests stay deterministic."""

    def __init__(self, dwell_minutes: int = 120) -> None:
        self.dwell_minutes = dwell_minutes

    def invoke(self, messages):
        payload = json.loads(messages[-1].content)
        entries = [
            {"place_id": dest["place_id"], "dwell_minutes": self.dwell_minutes, "reason": "test"}
            for dest in payload.get("destinations", [])
        ]

        class _Resp:
            pass

        resp = _Resp()
        resp.content = json.dumps(entries)
        return resp


def food_candidate(place_id: str = "food-1") -> dict:
    return {
        "place_id": place_id,
        "name": "Dinner House",
        "coords": {"lat": 10.1, "lng": 76.42},
        "rating": 4.4,
        "types": ["restaurant"],
        "primary_type": "restaurant",
    }


def test_build_route_uses_single_call_with_intermediate_waypoints() -> None:
    fake_gmaps = FakeGMaps(
        legs=[
            {"distance_meters": 40_000, "duration_seconds": 3600, "encoded_polyline": "leg-out"},
            {"distance_meters": 42_000, "duration_seconds": 4200, "encoded_polyline": "leg-back"},
        ]
    )

    result = build_route(
        base_state(duration_hours=6),
        gmaps_client=fake_gmaps,
        trip_start=datetime(2026, 5, 31, 7, 0),
        model=FakeLLM(),
    )

    assert len(fake_gmaps.route_calls) == 1
    call = fake_gmaps.route_calls[0]
    assert call["origin"] == {"lat": 9.9312, "lng": 76.2673}
    assert call["destination"] == {"lat": 9.9312, "lng": 76.2673}
    assert call["intermediates"] == [{"lat": 10.2859, "lng": 76.5696}]
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
    assert [entry["type"] for entry in result["timeline"]] == [
        "start",
        "destination",
        "departure",
        "return",
    ]


def test_build_route_chains_multiple_stops_in_order() -> None:
    fake_gmaps = FakeGMaps(
        legs=[
            {"distance_meters": 20_000, "duration_seconds": 1800, "encoded_polyline": "a"},
            {"distance_meters": 15_000, "duration_seconds": 1800, "encoded_polyline": "b"},
            {"distance_meters": 25_000, "duration_seconds": 1800, "encoded_polyline": "c"},
        ],
        distance_meters=60_000,
    )
    selected = [
        destination("dest-1", name="Beach", coords={"lat": 10.0, "lng": 76.4}),
        destination("dest-2", name="Fort", coords={"lat": 10.1, "lng": 76.5}),
    ]

    result = build_route(
        base_state(duration_hours=8, selected=selected),
        gmaps_client=fake_gmaps,
        trip_start=datetime(2026, 5, 31, 7, 0),
        model=FakeLLM(dwell_minutes=60),
    )

    assert fake_gmaps.route_calls[0]["intermediates"] == [
        {"lat": 10.0, "lng": 76.4},
        {"lat": 10.1, "lng": 76.5},
    ]
    destination_labels = [
        entry["label"] for entry in result["timeline"] if entry["type"] == "destination"
    ]
    assert destination_labels == ["Stop 1: Beach", "Stop 2: Fort"]
    # start, stop1 arrive, stop1 leave, stop2 arrive, stop2 leave, return
    types = [entry["type"] for entry in result["timeline"]]
    assert types == [
        "start",
        "destination",
        "departure",
        "destination",
        "departure",
        "return",
    ]
    assert [entry["time"] for entry in result["timeline"]] == [
        "07:00",
        "07:30",
        "08:30",
        "09:00",
        "10:00",
        "10:30",
    ]
    assert result["route"]["total_distance_meters"] == 60_000


def test_explicit_dinner_searches_food_along_route() -> None:
    fake_gmaps = FakeGMaps(
        legs=[
            {"distance_meters": 30_000, "duration_seconds": 3200, "encoded_polyline": "out"},
            {"distance_meters": 30_000, "duration_seconds": 3200, "encoded_polyline": "back"},
        ],
        food_results=[food_candidate("dinner-1")],
    )
    state = base_state(duration_hours=7)
    state["constraints"]["departure_time"] = "15:00"
    state["constraints"]["interests"] = ["food", "culture"]
    state["raw_messages"] = [
        {"role": "user", "content": "Starting at 3 pm and back around 10 pm. Include dinner."}
    ]

    result = build_route(
        state,
        gmaps_client=fake_gmaps,
        trip_start=datetime(2026, 5, 31, 15, 0),
        model=FakeLLM(),
    )

    assert fake_gmaps.food_search_calls
    assert result["food_availability"][0]["meal"] == "dinner"
    assert result["food_availability"][0]["status"] in {"route_options", "destination_options"}
    assert result["food_availability"][0]["recommended_places"][0]["place_id"] == "dinner-1"
    assert result["food_stops"][0]["name"] == "Dinner options near route"
    assert "Google Maps options: dinner-1." in result["food_stops"][0]["notes"]
    assert "food" in [entry["type"] for entry in result["timeline"]]


def test_food_oriented_destination_satisfies_explicit_dinner_without_extra_stop() -> None:
    fake_gmaps = FakeGMaps(
        legs=[
            {"distance_meters": 10_000, "duration_seconds": 1800, "encoded_polyline": "out"},
            {"distance_meters": 10_000, "duration_seconds": 1800, "encoded_polyline": "back"},
        ],
        food_results=[food_candidate("unused")],
    )
    state = base_state(
        duration_hours=5,
        selected=[
            {
                "place_id": "swargam",
                "name": "Swargam",
                "coords": {"lat": 10.0, "lng": 76.35},
                "description": "Food-oriented destination.",
                "notes": [],
                "types": ["restaurant"],
                "primary_type": "restaurant",
            }
        ],
    )
    state["constraints"]["departure_time"] = "17:00"
    state["raw_messages"] = [{"role": "user", "content": "Include dinner at Swargam."}]

    result = build_route(
        state,
        gmaps_client=fake_gmaps,
        trip_start=datetime(2026, 5, 31, 17, 0),
        model=FakeLLM(),
    )

    assert fake_gmaps.food_search_calls == []
    assert result["food_stops"] == []
    assert result["food_availability"][0]["status"] == "eat_at_destination"
    assert result["food_availability"][0]["meal"] == "dinner"
    assert "plan dinner there" in result["food_availability"][0]["notes"]
    destination_entry = next(
        entry for entry in result["timeline"] if entry["type"] == "destination"
    )
    assert "plan dinner there" in destination_entry["notes"]


def test_dinner_window_without_explicit_food_need_can_be_eat_at_home() -> None:
    fake_gmaps = FakeGMaps(
        legs=[
            {"distance_meters": 30_000, "duration_seconds": 3200, "encoded_polyline": "out"},
            {"distance_meters": 30_000, "duration_seconds": 3200, "encoded_polyline": "back"},
        ]
    )
    state = base_state(duration_hours=7)
    state["constraints"]["departure_time"] = "15:00"

    result = build_route(
        state,
        gmaps_client=fake_gmaps,
        trip_start=datetime(2026, 5, 31, 15, 0),
        model=FakeLLM(),
    )

    assert fake_gmaps.food_search_calls == []
    assert result["food_stops"] == []
    assert result["food_availability"][0]["status"] == "eat_at_home"
    assert result["food_availability"][0]["meal"] == "dinner"
    assert "dinner can be at home" in result["food_availability"][0]["notes"]


def test_remote_morning_destination_without_food_options_gets_carry_or_parcel_guidance() -> None:
    fake_gmaps = FakeGMaps(
        legs=[
            {"distance_meters": 70_000, "duration_seconds": 7200, "encoded_polyline": "out"},
            {"distance_meters": 70_000, "duration_seconds": 7200, "encoded_polyline": "back"},
        ],
        food_results=[],
    )
    state = base_state(
        duration_hours=8,
        selected=[destination("dest-1", types=["hiking_area"], primary_type="hiking_area")],
    )
    state["constraints"]["departure_time"] = "06:00"

    result = build_route(
        state,
        gmaps_client=fake_gmaps,
        trip_start=datetime(2026, 5, 31, 6, 0),
        model=FakeLLM(),
    )

    assert fake_gmaps.food_search_calls
    assert result["food_stops"] == []
    assert result["food_availability"][0]["meal"] == "breakfast"
    assert result["food_availability"][0]["status"] == "carry_or_parcel"
    assert "carry water/snacks" in result["food_availability"][0]["notes"]


def test_build_route_uses_departure_time_from_constraints() -> None:
    fake_gmaps = FakeGMaps(
        legs=[
            {"distance_meters": 40_000, "duration_seconds": 3600, "encoded_polyline": "out"},
            {"distance_meters": 40_000, "duration_seconds": 3600, "encoded_polyline": "back"},
        ]
    )
    state = base_state(duration_hours=6)
    state["constraints"]["departure_time"] = "09:30"

    result = build_route(state, gmaps_client=fake_gmaps, model=FakeLLM())

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
        model=FakeLLM(),
    )

    assert [call["travel_mode"] for call in fake_gmaps.route_calls] == ["TWO_WHEELER"]
