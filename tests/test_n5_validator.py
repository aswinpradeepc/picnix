import json

from langchain_core.messages import HumanMessage, SystemMessage

from graph.nodes.n5_validator import validate_structured_output


class FakeResponse:
    def __init__(self, content) -> None:
        self.content = content


class FakeModel:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.invocations = []

    def invoke(self, messages):
        self.invocations.append(messages)
        return FakeResponse(json.dumps(self.payload))


def base_state() -> dict:
    return {
        "raw_messages": [{"role": "user", "content": "Plan a quiet day trip from Kochi."}],
        "constraints": {
            "start_location": "Kochi",
            "departure_time": "07:00",
            "duration_hours": 6,
            "vehicle": "car",
            "interests": ["nature"],
        },
        "validated_candidates": [
            {
                "place_id": "dest-1",
                "name": "Athirappilly Falls",
                "coords": {"lat": 10.2859, "lng": 76.5696},
                "types": ["tourist_attraction"],
            },
            {
                "place_id": "dest-2",
                "name": "Fort Kochi",
                "coords": {"lat": 9.9657, "lng": 76.2428},
                "types": ["tourist_attraction"],
            },
        ],
        "presented_candidate_index": 0,
        "validated_destination": {
            "place_id": "dest-1",
            "name": "Athirappilly Falls",
            "coords": {"lat": 10.2859, "lng": 76.5696},
            "types": ["tourist_attraction"],
        },
        "user_confirmed": True,
        "route_attempt_count": 1,
        "route": {
            "geojson": {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[76.2673, 9.9312], [76.5696, 10.2859]],
                },
                "properties": {"type": "route"},
            },
            "total_distance_meters": 82000,
            "planned_duration_seconds": 14400,
        },
        "food_stops": [],
        "food_availability": [],
        "timeline": [
            {
                "time": "07:00",
                "label": "Depart Kochi",
                "coords": {"lat": 9.9312, "lng": 76.2673},
                "type": "start",
                "notes": "Start the trip.",
            },
            {
                "time": "08:00",
                "label": "Athirappilly Falls",
                "coords": {"lat": 10.2859, "lng": 76.5696},
                "type": "destination",
                "notes": "Spend 2 hr here.",
            },
            {
                "time": "10:00",
                "label": "Leave Athirappilly Falls",
                "coords": {"lat": 10.2859, "lng": 76.5696},
                "type": "return_departure",
                "notes": "Start the return journey.",
            },
            {
                "time": "11:00",
                "label": "Back at Kochi",
                "coords": {"lat": 9.9312, "lng": 76.2673},
                "type": "return",
                "notes": "Trip ends.",
            },
        ],
        "itinerary_draft": "stale itinerary",
        "claim_failures": [],
        "final_geojson": {"stale": True},
        "final_itinerary": "stale final",
    }


def test_validator_reports_timeline_completeness_error_without_model_call() -> None:
    state = base_state()
    state["timeline"][1] = {**state["timeline"][1], "label": ""}
    model = FakeModel([])

    result = validate_structured_output(state, model=model)

    assert result["claim_failures"] == [
        {
            "field": "timeline[1].label",
            "issue": "Timeline entry 1 is missing label.",
            "severity": "error",
        }
    ]
    assert model.invocations == []


def test_validator_reorders_out_of_order_timeline_as_warning() -> None:
    state = base_state()
    state["timeline"] = [
        state["timeline"][0],
        state["timeline"][2],
        state["timeline"][1],
        state["timeline"][3],
    ]
    model = FakeModel([])

    result = validate_structured_output(state, model=model)

    assert result["claim_failures"] == [
        {
            "field": "timeline",
            "issue": "Timeline entries were out of chronological order and were reordered.",
            "severity": "warning",
        }
    ]
    assert [entry["time"] for entry in result["timeline"]] == [
        "07:00",
        "08:00",
        "10:00",
        "11:00",
    ]
    assert len(model.invocations) == 1


def test_validator_reports_invalid_route_shape() -> None:
    state = base_state()
    state["route"]["geojson"]["geometry"]["coordinates"] = [[76.2673, 9.9312]]

    result = validate_structured_output(state, model=FakeModel([]))

    assert result["claim_failures"] == [
        {
            "field": "route.geojson.geometry.coordinates",
            "issue": "Route LineString must contain at least two coordinates.",
            "severity": "error",
        }
    ]


def test_validator_requires_explicit_meal_coverage() -> None:
    state = base_state()
    state["raw_messages"] = [
        {"role": "user", "content": "Start from Kochi at 7 and include dinner."}
    ]

    result = validate_structured_output(state, model=FakeModel([]))

    assert result["claim_failures"] == [
        {
            "field": "food_availability",
            "issue": "Explicit dinner request is missing from food_availability.",
            "severity": "error",
        }
    ]


def test_validator_reports_invalid_coords() -> None:
    state = base_state()
    state["timeline"][2]["coords"] = {"lat": 120.0, "lng": 76.5696}

    result = validate_structured_output(state, model=FakeModel([]))

    assert result["claim_failures"] == [
        {
            "field": "timeline[2].coords",
            "issue": "Coordinates must have lat in [-90, 90] and lng in [-180, 180].",
            "severity": "error",
        }
    ]


def test_validator_preserves_semantic_warning_only() -> None:
    model = FakeModel(
        [
            {
                "field": "timeline",
                "issue": "Destination dwell time is short but still plausible.",
                "severity": "warning",
            }
        ]
    )

    result = validate_structured_output(base_state(), model=model)

    assert result["claim_failures"] == [
        {
            "field": "timeline",
            "issue": "Destination dwell time is short but still plausible.",
            "severity": "warning",
        }
    ]
    assert "validated_candidates" not in result
    assert "route_attempt_count" not in result
    assert isinstance(model.invocations[0][0], SystemMessage)
    assert isinstance(model.invocations[0][1], HumanMessage)


def test_validator_error_removes_current_destination_and_increments_attempt_count() -> None:
    model = FakeModel(
        [
            {
                "field": "timeline",
                "issue": "Destination dwell time is implausibly short.",
                "severity": "error",
            }
        ]
    )

    result = validate_structured_output(base_state(), model=model)

    assert result["validated_candidates"] == [
        {
            "place_id": "dest-2",
            "name": "Fort Kochi",
            "coords": {"lat": 9.9657, "lng": 76.2428},
            "types": ["tourist_attraction"],
        }
    ]
    assert result["validated_destination"]["place_id"] == "dest-2"
    assert result["presented_candidate_index"] == 0
    assert result["user_confirmed"] is False
    assert result["route_attempt_count"] == 2
    assert result["route"] == {}
    assert result["timeline"] == []
