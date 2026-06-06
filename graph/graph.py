from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from graph.nodes.n1_intent import collect_intent
from graph.nodes.n2_isochrone import fetch_isochrone_candidates, route_trip_type
from graph.nodes.n3_validator import validate_destination
from graph.nodes.n4_route import build_route
from graph.state import TripState


VALIDATED_SUGGESTION_LIMIT = 5


def initial_trip_state() -> TripState:
    return {
        "raw_messages": [],
        "constraints": {},
        "clarification_round": 0,
        "isochrone_polygon": {},
        "candidates": [],
        "candidate_index": 0,
        "validated_candidates": [],
        "presented_candidate_index": 0,
        "validated_destination": {},
        "validation_failures": [],
        "user_confirmed": False,
        "route": {},
        "food_stops": [],
        "food_availability": [],
        "itinerary_draft": "",
        "claim_failures": [],
        "route_attempt_count": 0,
        "rewrite_count": 0,
        "final_geojson": {},
        "final_itinerary": "",
        "timeline": [],
    }


def apply_updates(state: TripState, updates: dict[str, Any]) -> TripState:
    return {**state, **updates}


def run_intent_turn(
    state: TripState,
    user_message: str | None = None,
    *,
    collector: Callable[..., dict[str, Any]] = collect_intent,
    model: Any | None = None,
) -> TripState:
    next_state = state
    if user_message:
        next_state = apply_updates(
            state,
            {
                "raw_messages": [
                    *state.get("raw_messages", []),
                    {"role": "user", "content": user_message},
                ]
            },
        )
    return apply_updates(next_state, collector(next_state, model=model))


def validate_until_destination(
    state: TripState,
    *,
    validator: Callable[[TripState], dict[str, Any]] | None = None,
    target_count: int = VALIDATED_SUGGESTION_LIMIT,
    max_attempts: int | None = None,
) -> TripState:
    next_state = state
    validate = validator or (lambda current: validate_destination(current))
    attempts = 0
    attempt_limit = max_attempts or len(next_state.get("candidates", []))

    while attempts < attempt_limit:
        if len(next_state.get("validated_candidates", [])) >= target_count:
            break
        if int(next_state.get("candidate_index", 0)) >= len(next_state.get("candidates", [])):
            break
        previous_index = int(next_state.get("candidate_index", 0))
        previous_valid_count = len(next_state.get("validated_candidates", []))
        next_state = apply_updates(next_state, validate(next_state))
        attempts += 1
        current_index = int(next_state.get("candidate_index", 0))
        current_valid_count = len(next_state.get("validated_candidates", []))
        if current_index == previous_index and current_valid_count == previous_valid_count:
            break

    validated_candidates = list(next_state.get("validated_candidates", []))
    if not validated_candidates:
        return apply_updates(
            next_state,
            {
                "validated_destination": {},
                "presented_candidate_index": 0,
            },
        )

    presented_index = min(
        int(next_state.get("presented_candidate_index", 0)),
        len(validated_candidates) - 1,
    )
    return apply_updates(
        next_state,
        {
            "presented_candidate_index": presented_index,
            "validated_destination": validated_candidates[presented_index],
        },
    )


def run_candidate_discovery(
    state: TripState,
    *,
    fetcher: Callable[[TripState], dict[str, Any]] = fetch_isochrone_candidates,
    validator: Callable[[TripState], dict[str, Any]] | None = None,
) -> TripState:
    with_candidates = apply_updates(state, fetcher(state))
    return validate_until_destination(with_candidates, validator=validator)


def run_route_builder(
    state: TripState,
    *,
    builder: Callable[[TripState], dict[str, Any]] = build_route,
) -> TripState:
    return apply_updates(state, builder(state))


def request_next_candidate(
    state: TripState,
    *,
    validator: Callable[[TripState], dict[str, Any]] | None = None,
) -> TripState:
    _ = validator
    validated_candidates = list(state.get("validated_candidates", []))
    next_index = int(state.get("presented_candidate_index", 0)) + 1
    next_destination = (
        validated_candidates[next_index]
        if next_index < len(validated_candidates)
        else {}
    )
    return apply_updates(
        state,
        {
            "presented_candidate_index": next_index,
            "validated_destination": next_destination,
            "user_confirmed": False,
        },
    )


def _has_constraints(state: TripState) -> str:
    if state.get("constraints"):
        return route_trip_type(state)
    return END


def _validation_result(state: TripState) -> str:
    validated_candidates = list(state.get("validated_candidates", []))
    if len(validated_candidates) < VALIDATED_SUGGESTION_LIMIT and int(
        state.get("candidate_index", 0)
    ) < len(state.get("candidates", [])):
        return "n3_validator"
    if validated_candidates:
        return "n4_route"
    return END


def future_multiday_node(state: TripState) -> dict[str, Any]:
    return {
        "final_itinerary": (
            "Multi-day planning is coming soon. For now, Picnix supports trips up to 14 hours."
        )
    }


def build_graph():
    workflow = StateGraph(TripState)
    workflow.add_node("n1_intent", collect_intent)
    workflow.add_node("n2_isochrone", fetch_isochrone_candidates)
    workflow.add_node("n3_validator", validate_destination)
    workflow.add_node("n4_route", build_route)
    workflow.add_node("future_multiday", future_multiday_node)

    workflow.add_edge(START, "n1_intent")
    workflow.add_conditional_edges(
        "n1_intent",
        _has_constraints,
        {
            "n2_isochrone": "n2_isochrone",
            "future_multiday": "future_multiday",
            END: END,
        },
    )
    workflow.add_edge("n2_isochrone", "n3_validator")
    workflow.add_conditional_edges(
        "n3_validator",
        _validation_result,
        {
            "n3_validator": "n3_validator",
            "n4_route": "n4_route",
            END: END,
        },
    )
    workflow.add_edge("n4_route", END)
    workflow.add_edge("future_multiday", END)

    return workflow.compile(checkpointer=MemorySaver(), interrupt_before=["n4_route"])
