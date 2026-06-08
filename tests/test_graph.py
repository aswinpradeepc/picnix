from graph.graph import (
    _structured_validation_result,
    apply_updates,
    build_graph,
    confirm_selection,
    initial_trip_state,
    load_more_candidates,
    run_final_formatter,
    run_itinerary_composer,
    run_candidate_discovery,
    run_intent_turn,
    run_route_builder,
    run_structured_validator,
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
    assert state["presented_candidate_indices"] == []
    assert state["selected_destinations"] == []
    assert state["max_destinations"] == 3
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


def test_confirm_selection_writes_chosen_destinations() -> None:
    state = initial_trip_state()
    state["validated_candidates"] = [{"name": "A"}, {"name": "B"}, {"name": "C"}]

    result = confirm_selection(state, [0, 2])

    assert result["selected_destinations"] == [{"name": "A"}, {"name": "C"}]
    assert result["user_confirmed"] is True


def test_confirm_selection_caps_at_max_destinations() -> None:
    state = initial_trip_state()
    state["max_destinations"] = 2
    state["validated_candidates"] = [{"name": "A"}, {"name": "B"}, {"name": "C"}]

    result = confirm_selection(state, [0, 1, 2])

    assert result["selected_destinations"] == [{"name": "A"}, {"name": "B"}]
    assert result["user_confirmed"] is True


def test_confirm_selection_with_no_choices_does_not_confirm() -> None:
    state = initial_trip_state()
    state["validated_candidates"] = [{"name": "A"}]

    result = confirm_selection(state, [])

    assert result["selected_destinations"] == []
    assert result["user_confirmed"] is False


def test_load_more_candidates_validates_additional_options() -> None:
    state = initial_trip_state()
    state["candidates"] = [{"name": "A"}, {"name": "B"}]
    state["candidate_index"] = 1
    state["validated_candidates"] = [{"name": "A"}]

    def fake_validator(next_state):
        return {
            "candidate_index": 2,
            "validated_candidates": [{"name": "A"}, {"name": "B"}],
        }

    result = load_more_candidates(state, validator=fake_validator, batch_size=3)

    assert result["validated_candidates"] == [{"name": "A"}, {"name": "B"}]


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


def test_run_structured_validator_applies_n5_update() -> None:
    state = initial_trip_state()
    state["route"] = {"total_distance_meters": 1000}

    def fake_validator(next_state):
        assert next_state["route"] == {"total_distance_meters": 1000}
        return {
            "claim_failures": [
                {
                    "field": "timeline",
                    "issue": "Destination dwell time is short.",
                    "severity": "warning",
                }
            ]
        }

    result = run_structured_validator(state, validator=fake_validator)

    assert result["claim_failures"] == [
        {
            "field": "timeline",
            "issue": "Destination dwell time is short.",
            "severity": "warning",
        }
    ]


def test_run_itinerary_composer_applies_n6_update() -> None:
    state = initial_trip_state()
    state["claim_failures"] = []

    def fake_composer(next_state):
        assert next_state["claim_failures"] == []
        return {"itinerary_draft": "Draft itinerary."}

    result = run_itinerary_composer(state, composer=fake_composer)

    assert result["itinerary_draft"] == "Draft itinerary."


def test_run_final_formatter_applies_n7_update() -> None:
    state = initial_trip_state()
    state["itinerary_draft"] = "Draft itinerary."

    def fake_formatter(next_state):
        assert next_state["itinerary_draft"] == "Draft itinerary."
        return {
            "final_geojson": {"type": "FeatureCollection", "features": []},
            "final_itinerary": "Draft itinerary.",
        }

    result = run_final_formatter(state, formatter=fake_formatter)

    assert result["final_geojson"] == {"type": "FeatureCollection", "features": []}
    assert result["final_itinerary"] == "Draft itinerary."


def test_structured_validation_result_routes_error_with_candidates_back_to_n4() -> None:
    state = initial_trip_state()
    state["claim_failures"] = [
        {
            "field": "timeline",
            "issue": "Destination dwell time is implausibly short.",
            "severity": "error",
        }
    ]
    state["selected_destinations"] = [{"place_id": "next"}]

    assert _structured_validation_result(state) == "n4_route"


def test_structured_validation_result_routes_clean_or_warning_to_n6() -> None:
    clean_state = initial_trip_state()
    warning_state = initial_trip_state()
    warning_state["claim_failures"] = [
        {
            "field": "timeline",
            "issue": "Minor warning.",
            "severity": "warning",
        }
    ]

    assert _structured_validation_result(clean_state) == "n6_composer"
    assert _structured_validation_result(warning_state) == "n6_composer"


def test_structured_validation_result_ends_error_when_no_candidates_remain() -> None:
    exhausted_state = initial_trip_state()
    exhausted_state["claim_failures"] = [
        {
            "field": "timeline",
            "issue": "No valid route.",
            "severity": "error",
        }
    ]

    assert _structured_validation_result(exhausted_state) == "__end__"


def test_build_graph_compiles_with_checkpointer() -> None:
    graph = build_graph()

    assert graph is not None
