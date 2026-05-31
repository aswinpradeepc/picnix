from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from graph.nodes.n1_intent import collect_intent
from graph.nodes.n2_isochrone import fetch_isochrone_candidates, route_trip_type
from graph.nodes.n3_validator import validate_destination
from graph.state import TripState


def initial_trip_state() -> TripState:
    return {
        "raw_messages": [],
        "constraints": {},
        "clarification_round": 0,
        "isochrone_polygon": {},
        "candidates": [],
        "candidate_index": 0,
        "validated_destination": {},
        "validation_failures": [],
        "user_confirmed": False,
        "route": {},
        "food_stops": [],
        "itinerary_draft": "",
        "claim_failures": [],
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
    max_attempts: int = 5,
) -> TripState:
    next_state = state
    validate = validator or (lambda current: validate_destination(current))

    for _ in range(max_attempts):
        if next_state.get("validated_destination"):
            break
        if int(next_state.get("candidate_index", 0)) >= len(next_state.get("candidates", [])):
            break
        next_state = apply_updates(next_state, validate(next_state))

    return next_state


def run_candidate_discovery(
    state: TripState,
    *,
    fetcher: Callable[[TripState], dict[str, Any]] = fetch_isochrone_candidates,
    validator: Callable[[TripState], dict[str, Any]] | None = None,
) -> TripState:
    with_candidates = apply_updates(state, fetcher(state))
    return validate_until_destination(with_candidates, validator=validator)


def request_next_candidate(
    state: TripState,
    *,
    validator: Callable[[TripState], dict[str, Any]] | None = None,
) -> TripState:
    current_destination = state.get("validated_destination", {})
    current_name = current_destination.get("name", "candidate")
    next_state = apply_updates(
        state,
        {
            "candidate_index": int(state.get("candidate_index", 0)) + 1,
            "validated_destination": {},
            "validation_failures": [
                *state.get("validation_failures", []),
                f"{current_name} rejected: user requested another option",
            ],
        },
    )
    return validate_until_destination(next_state, validator=validator)


def _has_constraints(state: TripState) -> str:
    if state.get("constraints"):
        return route_trip_type(state)
    return END


def _validation_result(state: TripState) -> str:
    if state.get("validated_destination"):
        return END
    if int(state.get("candidate_index", 0)) >= len(state.get("candidates", [])):
        return END
    return "n3_validator"


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
            END: END,
        },
    )
    workflow.add_edge("future_multiday", END)

    return workflow.compile(checkpointer=MemorySaver())
