"""Graph-level tests for the CS5 topology and the interrupt-driven app flow.

Node functions are monkeypatched on the graph.graph module before build_graph() so the
compiled graph runs with stub nodes (except N7, which runs for real to prove it resets
plan_edit_mode). This exercises the exact mechanics app.py relies on: invoke-after-END
for chat turns, update_state(as_node="n3_validator") re-arming, static interrupts before
n4_route/n8_editor, and the advance_graph auto-resume rule.
"""

from typing import Any

import graph.graph as graph_module
from langgraph.checkpoint.memory import MemorySaver
from app import advance_graph
from graph.graph import build_graph, initial_trip_state, selection_updates


CONSTRAINTS = {
    "start_location": "Kochi",
    "departure_time": "08:00",
    "duration_hours": 8.0,
    "group_size": 2,
    "vehicle": "car",
    "interests": ["nature"],
    "budget_feel": "medium",
}

CANDIDATES = [
    {"place_id": "A", "name": "Falls", "primary_type": "waterfall"},
    {"place_id": "B", "name": "Beach", "primary_type": "beach"},
    {"place_id": "C", "name": "Museum", "primary_type": "museum"},
]


def fake_collect_intent(state: dict, **_: Any) -> dict:
    messages = list(state.get("raw_messages", []))
    if not messages:
        return {
            "raw_messages": [{"role": "assistant", "content": "Where to?"}],
            "clarification_prompt": {},
        }
    return {
        "raw_messages": [*messages, {"role": "assistant", "content": "Got it!"}],
        "constraints": CONSTRAINTS,
        "clarification_prompt": {},
    }


def fake_fetch_candidates(state: dict, **_: Any) -> dict:
    return {"candidates": list(CANDIDATES), "candidate_index": 0}


def fake_validate_destination(state: dict, **_: Any) -> dict:
    return {
        "candidate_index": len(state.get("candidates", [])),
        "validated_candidates": list(state.get("candidates", [])),
    }


def fake_build_route(state: dict, **_: Any) -> dict:
    stops = state.get("selected_destinations", [])
    return {
        "route": {"total_distance_meters": 1000 * len(stops)},
        "timeline": [
            {"time": "08:00", "label": "Depart", "coords": {"lat": 10.0, "lng": 76.3},
             "type": "start", "notes": "go"},
        ],
        "food_stops": [],
        "food_availability": [],
    }


def fake_validate_structured_output(state: dict, **_: Any) -> dict:
    return {"claim_failures": []}


def fake_compose_itinerary(state: dict, **_: Any) -> dict:
    names = ", ".join(d["name"] for d in state.get("selected_destinations", []))
    return {"itinerary_draft": f"Visit {names}."}


def fake_edit_plan(state: dict, **_: Any) -> dict:
    """Stub N8: drop the first stop, mirroring the real node's state contract."""
    remaining = list(state.get("selected_destinations", []))[1:] or list(
        state.get("selected_destinations", [])
    )
    return {
        "selected_destinations": remaining,
        "edit_history": [
            *state.get("edit_history", []),
            {
                "instruction": state.get("edit_instruction", ""),
                "timestamp": "2026-06-10T00:00:00",
                "resulting_destinations": [d["name"] for d in remaining],
                "unfulfilled": [],
            },
        ],
        "edit_notice": "Dropped the first stop.",
        "edit_instruction": "",
        "user_confirmed": True,
        "route_attempt_count": 0,
        "route": {},
        "timeline": [],
        "food_stops": [],
        "food_availability": [],
        "claim_failures": [],
        "removal_notice": "",
        "itinerary_draft": "",
        "final_geojson": {},
        "final_itinerary": "",
    }


def patched_graph(monkeypatch):
    monkeypatch.setattr(graph_module, "collect_intent", fake_collect_intent)
    monkeypatch.setattr(graph_module, "fetch_isochrone_candidates", fake_fetch_candidates)
    monkeypatch.setattr(graph_module, "validate_destination", fake_validate_destination)
    monkeypatch.setattr(graph_module, "build_route", fake_build_route)
    monkeypatch.setattr(graph_module, "validate_structured_output", fake_validate_structured_output)
    monkeypatch.setattr(graph_module, "compose_itinerary", fake_compose_itinerary)
    monkeypatch.setattr(graph_module, "edit_plan", fake_edit_plan)
    # n7_formatter runs for real: it must reset plan_edit_mode.
    return build_graph(checkpointer=MemorySaver())


def test_compiled_graph_interrupts_before_n4_and_n8() -> None:
    compiled = build_graph(checkpointer=MemorySaver())

    assert set(compiled.interrupt_before_nodes) == {"n4_route", "n8_editor"}


def test_n7_has_unconditional_edge_to_n8_and_no_end_edge() -> None:
    drawable = build_graph(checkpointer=MemorySaver()).get_graph()
    n7_targets = {edge.target for edge in drawable.edges if edge.source == "n7_formatter"}

    assert n7_targets == {"n8_editor"}


def test_n8_routes_back_to_n4() -> None:
    drawable = build_graph(checkpointer=MemorySaver()).get_graph()
    n8_targets = {edge.target for edge in drawable.edges if edge.source == "n8_editor"}

    assert n8_targets == {"n4_route"}


def test_initial_state_has_cs5_defaults() -> None:
    state = initial_trip_state()

    assert state["plan_edit_mode"] is False
    assert state["edit_instruction"] == ""
    assert state["edit_history"] == []
    assert state["edit_notice"] == ""


def test_full_flow_parks_at_n8_and_supports_successive_edits(monkeypatch) -> None:
    graph = patched_graph(monkeypatch)
    config = {"configurable": {"thread_id": "flow-test"}}

    # Greeting turn: N1 runs, no constraints yet, thread ends awaiting chat input.
    graph.invoke(initial_trip_state(), config)
    snapshot = graph.get_state(config)
    assert snapshot.next == ()
    assert snapshot.values["raw_messages"][0]["role"] == "assistant"

    # Chat turn that lands constraints: runs N1 → N2 → N3 and pauses at the
    # n4_route interrupt with the selection gallery's data ready.
    messages = [*snapshot.values["raw_messages"], {"role": "user", "content": "plan it"}]
    graph.invoke({"raw_messages": messages}, config)
    snapshot = graph.get_state(config)
    assert snapshot.next == ("n4_route",)
    assert len(snapshot.values["validated_candidates"]) == 3
    assert snapshot.values["user_confirmed"] is False

    # Confirm a selection the way app.py does, then advance: the run flows
    # N4 → N5 → N6 → N7 and parks at the n8_editor interrupt with the plan shown.
    graph.update_state(
        config,
        selection_updates(snapshot.values, [0, 1, 2]),
        as_node="n3_validator",
    )
    graph.invoke(None, config)
    snapshot = advance_graph(graph, config)
    assert snapshot.next == ("n8_editor",)
    assert snapshot.values["final_itinerary"] == "Visit Falls, Beach, Museum."
    assert snapshot.values["plan_edit_mode"] is False

    # Three successive edits: each resumes through N8 → N4 (auto-resumed) → … → N7
    # and parks at n8_editor again with one more edit_history entry.
    expected = ["Visit Beach, Museum.", "Visit Museum.", "Visit Museum."]
    for index, expected_itinerary in enumerate(expected, start=1):
        graph.update_state(
            config,
            {"edit_instruction": f"edit {index}", "plan_edit_mode": True},
        )
        graph.invoke(None, config)
        snapshot = advance_graph(graph, config)
        assert snapshot.next == ("n8_editor",)
        assert snapshot.values["final_itinerary"] == expected_itinerary
        assert len(snapshot.values["edit_history"]) == index
        assert snapshot.values["plan_edit_mode"] is False
        assert snapshot.values["edit_instruction"] == ""
