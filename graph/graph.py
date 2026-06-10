from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from config.settings import SETTINGS
from graph.nodes.n1_intent import collect_intent
from graph.nodes.n2_isochrone import fetch_isochrone_candidates, route_trip_type
from graph.nodes.n3_validator import validate_destination
from graph.nodes.n4_route import build_route
from graph.nodes.n5_validator import validate_structured_output
from graph.nodes.n6_composer import compose_itinerary
from graph.nodes.n7_formatter import format_final_output
from graph.nodes.n8_editor import edit_plan
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
        "presented_candidate_indices": [],
        "selected_destinations": [],
        "max_destinations": 3,
        "removal_notice": "",
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
        "plan_edit_mode": False,
        "edit_instruction": "",
        "edit_history": [],
        "edit_notice": "",
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

    return next_state


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


def run_structured_validator(
    state: TripState,
    *,
    validator: Callable[[TripState], dict[str, Any]] = validate_structured_output,
) -> TripState:
    return apply_updates(state, validator(state))


def run_itinerary_composer(
    state: TripState,
    *,
    composer: Callable[[TripState], dict[str, Any]] = compose_itinerary,
) -> TripState:
    return apply_updates(state, composer(state))


def run_final_formatter(
    state: TripState,
    *,
    formatter: Callable[[TripState], dict[str, Any]] = format_final_output,
) -> TripState:
    return apply_updates(state, formatter(state))


def selection_updates(
    state: TripState,
    selected_indices: list[int],
) -> dict[str, Any]:
    """State updates that write the candidates at `selected_indices` into `selected_destinations` and mark the trip confirmed."""
    candidates = list(state.get("validated_candidates", []))
    max_destinations = int(state.get("max_destinations", 3))
    chosen = [
        candidates[index]
        for index in selected_indices
        if 0 <= index < len(candidates)
    ][:max_destinations]
    return {
        "selected_destinations": chosen,
        "presented_candidate_indices": list(range(len(candidates))),
        "user_confirmed": bool(chosen),
        "removal_notice": "",
    }


def confirm_selection(
    state: TripState,
    selected_indices: list[int],
) -> TripState:
    """Apply `selection_updates` to a plain state dict (test/manual-pipeline helper)."""
    return apply_updates(state, selection_updates(state, selected_indices))


def load_more_candidates(
    state: TripState,
    *,
    validator: Callable[[TripState], dict[str, Any]] | None = None,
    batch_size: int = 3,
) -> TripState:
    """Validate more raw candidates into the `validated_candidates` queue so the user has additional options to pick from."""
    current_count = len(state.get("validated_candidates", []))
    return validate_until_destination(
        state,
        validator=validator,
        target_count=current_count + batch_size,
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


def _structured_validation_result(state: TripState) -> str:
    has_error = any(
        failure.get("severity") == "error"
        for failure in state.get("claim_failures", [])
    )
    if has_error and state.get("selected_destinations"):
        return "n4_route"
    if not has_error:
        return "n6_composer"
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
    workflow.add_node("n5_validator", validate_structured_output)
    workflow.add_node("n6_composer", compose_itinerary)
    workflow.add_node("n7_formatter", format_final_output)
    workflow.add_node("n8_editor", edit_plan)
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
    workflow.add_edge("n4_route", "n5_validator")
    workflow.add_conditional_edges(
        "n5_validator",
        _structured_validation_result,
        {
            "n4_route": "n4_route",
            "n6_composer": "n6_composer",
            END: END,
        },
    )
    workflow.add_edge("n6_composer", "n7_formatter")
    # N7 → N8 is unconditional: the graph always parks at the n8_editor interrupt with the
    # plan shown. A user who never edits simply leaves the thread parked there.
    workflow.add_edge("n7_formatter", "n8_editor")
    workflow.add_edge("n8_editor", "n4_route")
    workflow.add_edge("future_multiday", END)

    return workflow.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["n4_route", "n8_editor"],
    )


if SETTINGS.debug:
    from tools.graph_viz import export_graph_diagram
    export_graph_diagram()
