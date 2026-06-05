from graph.graph import (
    apply_updates,
    build_graph,
    initial_trip_state,
    request_next_candidate,
    run_candidate_discovery,
    run_intent_turn,
    run_route_builder,
    validate_until_destination,
)


def test_initial_trip_state_has_expected_defaults() -> None:
    state = initial_trip_state()

    assert state["raw_messages"] == []
    assert state["constraints"] == {}
    assert state["clarification_round"] == 0
    assert state["candidates"] == []
    assert state["candidate_index"] == 0
    assert state["validated_candidates"] == []
    assert state["presented_candidate_index"] == 0
    assert state["validated_destination"] == {}
    assert state["validation_failures"] == []
    assert state["user_confirmed"] is False
    assert state["food_availability"] == []
    assert state["timeline"] == []


def test_apply_updates_returns_new_state_without_mutating_original() -> None:
    state = initial_trip_state()

    updated = apply_updates(state, {"constraints": {"duration_hours": 8}})

    assert state["constraints"] == {}
    assert updated["constraints"] == {"duration_hours": 8}


def test_run_intent_turn_appends_user_message_and_applies_node_update() -> None:
    state = initial_trip_state()

    def fake_collector(next_state, *, model=None):
        assert next_state["raw_messages"][-1] == {
            "role": "user",
            "content": "Plan a trip",
        }
        return {
            "raw_messages": [
                *next_state["raw_messages"],
                {"role": "assistant", "content": "Where from?"},
            ],
            "clarification_round": 1,
        }

    result = run_intent_turn(state, "Plan a trip", collector=fake_collector)

    assert result["raw_messages"][-1]["content"] == "Where from?"
    assert result["clarification_round"] == 1


def test_validate_until_destination_builds_validated_candidate_queue() -> None:
    state = initial_trip_state()
    state["candidate_index"] = 0
    state["candidates"] = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    calls = []

    def fake_validator(next_state):
        calls.append(next_state["candidate_index"])
        if next_state["candidate_index"] == 0:
            return {
                "candidate_index": 1,
                "validated_candidates": [{"name": "A"}],
            }
        if next_state["candidate_index"] == 1:
            return {
                "candidate_index": 2,
                "validation_failures": ["B rejected"],
            }
        return {
            "candidate_index": 3,
            "validation_failures": ["B rejected"],
            "validated_candidates": [{"name": "A"}, {"name": "C"}],
        }

    result = validate_until_destination(state, validator=fake_validator, target_count=2)

    assert calls == [0, 1, 2]
    assert result["validated_candidates"] == [{"name": "A"}, {"name": "C"}]
    assert result["presented_candidate_index"] == 0
    assert result["validated_destination"] == {"name": "A"}
    assert result["validation_failures"] == ["B rejected"]


def test_run_candidate_discovery_fetches_then_validates() -> None:
    state = initial_trip_state()
    state["constraints"] = {"duration_hours": 8}

    def fake_fetcher(next_state):
        assert next_state["constraints"] == {"duration_hours": 8}
        return {
            "candidates": [{"name": "A"}],
            "candidate_index": 0,
            "validated_candidates": [],
            "presented_candidate_index": 0,
            "validated_destination": {},
            "isochrone_polygon": {"properties": {"center": {"lat": 1, "lng": 2}}},
        }

    def fake_validator(next_state):
        assert next_state["candidates"] == [{"name": "A"}]
        return {
            "candidate_index": 1,
            "validated_candidates": [{"name": "A"}],
        }

    result = run_candidate_discovery(
        state,
        fetcher=fake_fetcher,
        validator=fake_validator,
    )

    assert result["validated_candidates"] == [{"name": "A"}]
    assert result["validated_destination"] == {"name": "A"}


def test_request_next_candidate_advances_within_validated_queue() -> None:
    state = initial_trip_state()
    state["validated_candidates"] = [{"name": "A"}, {"name": "B"}]
    state["presented_candidate_index"] = 0
    state["validated_destination"] = {"name": "A"}
    state["validation_failures"] = ["Hidden raw candidate rejected: closed"]

    result = request_next_candidate(state)

    assert result["presented_candidate_index"] == 1
    assert result["validated_destination"] == {"name": "B"}
    assert result["validation_failures"] == ["Hidden raw candidate rejected: closed"]


def test_request_next_candidate_clears_destination_when_queue_is_exhausted() -> None:
    state = initial_trip_state()
    state["validated_candidates"] = [{"name": "A"}]
    state["presented_candidate_index"] = 0
    state["validated_destination"] = {"name": "A"}

    result = request_next_candidate(state)

    assert result["presented_candidate_index"] == 1
    assert result["validated_destination"] == {}


def test_run_route_builder_applies_route_node_update() -> None:
    state = initial_trip_state()
    state["user_confirmed"] = True

    def fake_builder(next_state):
        assert next_state["user_confirmed"] is True
        return {
            "route": {"total_distance_meters": 1000},
            "food_stops": [],
            "timeline": [{"time": "07:00", "label": "Depart"}],
        }

    result = run_route_builder(state, builder=fake_builder)

    assert result["route"] == {"total_distance_meters": 1000}
    assert result["timeline"] == [{"time": "07:00", "label": "Depart"}]


def test_build_graph_compiles_with_checkpointer() -> None:
    graph = build_graph()

    assert graph is not None
