import json

from graph.nodes.n8_editor import (
    DURATION_CHANGE_WARNING,
    EDIT_FAILURE_NOTICE,
    EDITOR_RESPONSE_SCHEMA,
    apply_edit_result,
    candidate_universe,
    edit_plan,
)


def base_state() -> dict:
    return {
        "selected_destinations": [
            {"place_id": "A", "name": "Athirappilly Falls", "primary_type": "waterfall"},
            {"place_id": "B", "name": "Marari Beach", "primary_type": "beach"},
        ],
        "validated_candidates": [
            {"place_id": "A", "name": "Athirappilly Falls", "primary_type": "waterfall"},
            {"place_id": "B", "name": "Marari Beach", "primary_type": "beach"},
            {"place_id": "C", "name": "Hill Palace Museum", "primary_type": "museum"},
        ],
        "constraints": {"departure_time": "08:00", "duration_hours": 8.0},
        "max_destinations": 3,
        "edit_instruction": "swap the beach for the museum",
        "edit_history": [],
        "route": {"total_distance_meters": 1},
        "timeline": [{"time": "08:00"}],
        "food_stops": [{"name": "cafe"}],
        "food_availability": [{"meal": "lunch"}],
        "claim_failures": [{"field": "x", "issue": "y", "severity": "warning"}],
        "removal_notice": "old notice",
        "itinerary_draft": "old draft",
        "final_geojson": {"type": "FeatureCollection"},
        "final_itinerary": "old itinerary",
        "route_attempt_count": 2,
    }


def llm_result(**overrides) -> dict:
    result = {
        "updated_place_ids": ["A", "C"],
        "departure_time": None,
        "duration_hours": None,
        "edit_summary": "Swapped the beach for the museum.",
        "unfulfilled": [],
    }
    result.update(overrides)
    return result


def test_candidate_universe_unions_selected_and_validated() -> None:
    universe = candidate_universe(base_state())

    assert set(universe) == {"A", "B", "C"}


def test_apply_edit_result_maps_ids_to_real_destination_dicts() -> None:
    state = base_state()

    updates = apply_edit_result(llm_result(), state)

    assert updates["selected_destinations"] == [
        state["validated_candidates"][0],
        state["validated_candidates"][2],
    ]
    assert updates["user_confirmed"] is True
    assert updates["route_attempt_count"] == 0
    assert updates["edit_instruction"] == ""


def test_apply_edit_result_drops_unknown_and_duplicate_ids() -> None:
    updates = apply_edit_result(
        llm_result(updated_place_ids=["A", "Z", "A", "C"]),
        base_state(),
    )

    assert [d["place_id"] for d in updates["selected_destinations"]] == ["A", "C"]


def test_apply_edit_result_falls_back_to_unchanged_plan_when_no_ids_survive() -> None:
    state = base_state()

    updates = apply_edit_result(llm_result(updated_place_ids=["Z", "Y"]), state)

    assert updates["selected_destinations"] == state["selected_destinations"]
    assert "unchanged" in updates["edit_notice"]


def test_apply_edit_result_never_writes_an_empty_destination_list() -> None:
    updates = apply_edit_result(llm_result(updated_place_ids=[]), base_state())

    assert updates["selected_destinations"] == base_state()["selected_destinations"]


def test_apply_edit_result_falls_back_when_over_max_destinations() -> None:
    state = base_state()
    state["max_destinations"] = 2

    updates = apply_edit_result(llm_result(updated_place_ids=["A", "B", "C"]), state)

    assert updates["selected_destinations"] == state["selected_destinations"]
    assert "2" in updates["edit_notice"]


def test_apply_edit_result_applies_valid_timing_changes() -> None:
    updates = apply_edit_result(
        llm_result(departure_time="07:00", duration_hours=4.0),
        base_state(),
    )

    assert updates["constraints"]["departure_time"] == "07:00"
    assert updates["constraints"]["duration_hours"] == 4.0
    assert DURATION_CHANGE_WARNING in updates["edit_notice"]


def test_apply_edit_result_rejects_invalid_timing_values() -> None:
    updates = apply_edit_result(
        llm_result(departure_time="25:99", duration_hours=20),
        base_state(),
    )

    assert updates["constraints"]["departure_time"] == "08:00"
    assert updates["constraints"]["duration_hours"] == 8.0
    assert "HH:MM" in updates["edit_notice"]
    assert "14" in updates["edit_notice"]


def test_apply_edit_result_resets_route_artifacts_like_n5_replan() -> None:
    updates = apply_edit_result(llm_result(), base_state())

    assert updates["route"] == {}
    assert updates["timeline"] == []
    assert updates["food_stops"] == []
    assert updates["food_availability"] == []
    assert updates["claim_failures"] == []
    assert updates["itinerary_draft"] == ""
    assert updates["final_geojson"] == {}
    assert updates["final_itinerary"] == ""
    assert updates["removal_notice"] == ""


def test_apply_edit_result_appends_edit_history_with_names() -> None:
    unfulfilled = [{"request": "add a zoo", "reason": "not in the validated pool for this trip"}]

    updates = apply_edit_result(llm_result(unfulfilled=unfulfilled), base_state())

    assert len(updates["edit_history"]) == 1
    entry = updates["edit_history"][0]
    assert entry["instruction"] == "swap the beach for the museum"
    assert entry["resulting_destinations"] == ["Athirappilly Falls", "Hill Palace Museum"]
    assert entry["unfulfilled"] == unfulfilled
    assert entry["timestamp"]
    assert "not in the validated pool" in updates["edit_notice"]


class FakeModel:
    def __init__(self, content) -> None:
        self.content = content
        self.invocations: list = []

    def invoke(self, messages):
        self.invocations.append(messages)

        class Response:
            pass

        response = Response()
        response.content = self.content
        return response


def test_edit_plan_runs_llm_and_enforces_result() -> None:
    model = FakeModel(json.dumps(llm_result()))

    updates = edit_plan(base_state(), model=model)

    assert [d["place_id"] for d in updates["selected_destinations"]] == ["A", "C"]
    assert len(model.invocations) == 1
    prompt_payload = json.loads(model.invocations[0][1].content)
    assert prompt_payload["edit_instruction"] == "swap the beach for the museum"
    assert [p["place_id"] for p in prompt_payload["current_plan"]] == ["A", "B"]
    assert [p["place_id"] for p in prompt_payload["available_alternatives"]] == ["C"]


def test_edit_plan_handles_list_content_with_text_parts() -> None:
    model = FakeModel([{"type": "text", "text": json.dumps(llm_result())}])

    updates = edit_plan(base_state(), model=model)

    assert [d["place_id"] for d in updates["selected_destinations"]] == ["A", "C"]


def test_edit_plan_keeps_plan_and_parks_cleanly_on_garbage_response() -> None:
    state = base_state()

    updates = edit_plan(state, model=FakeModel("not json at all"))

    assert updates["selected_destinations"] == state["selected_destinations"]
    assert updates["edit_notice"] == EDIT_FAILURE_NOTICE
    assert updates["user_confirmed"] is True
    assert updates["edit_instruction"] == ""
    assert updates["route"] == {}
    assert len(updates["edit_history"]) == 1
    assert updates["edit_history"][0]["unfulfilled"][0]["reason"] == "editor error"


def test_edit_plan_keeps_plan_on_model_exception() -> None:
    class ExplodingModel:
        def invoke(self, messages):
            raise RuntimeError("api down")

    state = base_state()

    updates = edit_plan(state, model=ExplodingModel())

    assert updates["selected_destinations"] == state["selected_destinations"]
    assert updates["edit_notice"] == EDIT_FAILURE_NOTICE


def test_editor_response_schema_requires_ids_summary_and_unfulfilled() -> None:
    assert set(EDITOR_RESPONSE_SCHEMA["required"]) == {
        "updated_place_ids",
        "edit_summary",
        "unfulfilled",
    }
    assert EDITOR_RESPONSE_SCHEMA["properties"]["updated_place_ids"]["items"] == {
        "type": "string"
    }
