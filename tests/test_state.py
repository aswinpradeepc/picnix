import importlib
import importlib.util
from typing import get_type_hints


EXPECTED_FIELDS = [
    "raw_messages",
    "constraints",
    "clarification_round",
    "clarification_prompt",
    "isochrone_polygon",
    "candidates",
    "candidate_index",
    "validated_candidates",
    "presented_candidate_indices",
    "selected_destinations",
    "max_destinations",
    "removal_notice",
    "validation_failures",
    "user_confirmed",
    "route",
    "food_stops",
    "food_availability",
    "itinerary_draft",
    "claim_failures",
    "route_attempt_count",
    "rewrite_count",
    "final_geojson",
    "final_itinerary",
    "timeline",
]


EXPECTED_TYPES = {
    "raw_messages": list[dict],
    "constraints": dict,
    "clarification_round": int,
    "clarification_prompt": dict,
    "isochrone_polygon": dict,
    "candidates": list[dict],
    "candidate_index": int,
    "validated_candidates": list[dict],
    "presented_candidate_indices": list[int],
    "selected_destinations": list[dict],
    "max_destinations": int,
    "removal_notice": str,
    "validation_failures": list[str],
    "user_confirmed": bool,
    "route": dict,
    "food_stops": list[dict],
    "food_availability": list[dict],
    "itinerary_draft": str,
    "claim_failures": list[dict],
    "route_attempt_count": int,
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
