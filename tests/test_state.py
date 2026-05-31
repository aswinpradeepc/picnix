import importlib
import importlib.util
from typing import get_type_hints


EXPECTED_FIELDS = [
    "raw_messages",
    "constraints",
    "clarification_round",
    "isochrone_polygon",
    "candidates",
    "candidate_index",
    "validated_destination",
    "validation_failures",
    "user_confirmed",
    "route",
    "food_stops",
    "itinerary_draft",
    "claim_failures",
    "rewrite_count",
    "final_geojson",
    "final_itinerary",
    "timeline",
]


EXPECTED_TYPES = {
    "raw_messages": list[dict],
    "constraints": dict,
    "clarification_round": int,
    "isochrone_polygon": dict,
    "candidates": list[dict],
    "candidate_index": int,
    "validated_destination": dict,
    "validation_failures": list[str],
    "user_confirmed": bool,
    "route": dict,
    "food_stops": list[dict],
    "itinerary_draft": str,
    "claim_failures": list[dict],
    "rewrite_count": int,
    "final_geojson": dict,
    "final_itinerary": str,
    "timeline": list[dict],
}


def test_trip_state_module_exists() -> None:
    assert importlib.util.find_spec("graph.state") is not None


def test_trip_state_schema_matches_design_context() -> None:
    state_module = importlib.import_module("graph.state")

    assert hasattr(state_module, "TripState")
    assert list(state_module.TripState.__annotations__) == EXPECTED_FIELDS
    assert get_type_hints(state_module.TripState) == EXPECTED_TYPES
    assert state_module.TripState.__total__ is True
