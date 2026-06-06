from app import (
    destination_empty_message,
    destination_prompt_message,
    destination_summary,
    final_geojson_center,
    food_availability_rows,
    format_duration,
    format_km,
    run_confirmed_destination_pipeline,
    show_destination_actions,
    timeline_rows,
)


def test_format_km_formats_meters() -> None:
    assert format_km(17047) == "17.0 km"


def test_format_duration_formats_seconds() -> None:
    assert format_duration(1869) == "31 min"
    assert format_duration(7200) == "2 hr"
    assert format_duration(7320) == "2 hr 2 min"


def test_destination_summary_uses_available_destination_fields() -> None:
    assert destination_summary(
        {
            "name": "Mattancherry Palace",
            "distance_meters": 17047,
            "travel_time_seconds": 1869,
            "description": "Historic palace.",
            "notes": ["Check timings before leaving."],
        }
    ) == {
        "name": "Mattancherry Palace",
        "distance": "17.0 km",
        "duration": "31 min",
        "description": "Historic palace.",
        "notes": ["Check timings before leaving."],
    }


def test_destination_empty_message_hides_validation_failures_from_suggestion_surface() -> None:
    state = {
        "constraints": {"start_location": "Kochi"},
        "candidates": [{"name": "Hidden Raw Candidate"}],
        "validated_candidates": [],
        "validation_failures": ["Hidden Raw Candidate rejected: closed during trip window"],
    }

    assert destination_empty_message(state) == (
        "No more open and reachable suggestions found for this trip window."
    )


def test_destination_prompt_message_flags_reprompt_after_n5_rejection() -> None:
    state = {
        "route_attempt_count": 1,
        "user_confirmed": False,
        "validated_destination": {"name": "Fort Kochi"},
    }

    assert destination_prompt_message(state) == (
        "That destination couldn't be fully planned - here are the remaining options."
    )
    assert destination_prompt_message({"route_attempt_count": 0}) == ""


def test_timeline_rows_shapes_entries_for_streamlit_table() -> None:
    assert timeline_rows(
        [
            {
                "time": "07:00",
                "label": "Depart Kochi",
                "type": "start",
                "notes": "Start the trip.",
            }
        ]
    ) == [
        {
            "Time": "07:00",
            "Stop": "Depart Kochi",
            "Type": "start",
            "Notes": "Start the trip.",
        }
    ]


def test_food_availability_rows_shapes_entries_for_streamlit_table() -> None:
    assert food_availability_rows(
        [
            {
                "meal": "dinner",
                "status": "eat_at_home",
                "time": "18:50",
                "notes": "Dinner can be at home.",
            }
        ]
    ) == [
        {
            "Meal": "dinner",
            "Decision": "eat at home",
            "Time": "18:50",
            "Notes": "Dinner can be at home.",
        }
    ]


def test_show_destination_actions_hides_buttons_after_user_confirms() -> None:
    assert show_destination_actions({"user_confirmed": False}) is True
    assert show_destination_actions({"user_confirmed": True}) is False


def test_final_geojson_center_uses_feature_coordinates() -> None:
    center = final_geojson_center(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[76.2, 9.9], [76.6, 10.3]],
                    },
                    "properties": {"type": "route"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [76.4, 10.1]},
                    "properties": {"type": "waypoint"},
                },
            ],
        }
    )

    assert center == {"latitude": 10.1, "longitude": 76.4, "zoom": 9}


def test_pipeline_runs_through_n7_when_n5_allows_plan() -> None:
    state = {"user_confirmed": True}
    calls = []

    def fake_route(next_state):
        calls.append("route")
        return {**next_state, "route": {"total_distance_meters": 1000}}

    def fake_validator(next_state):
        calls.append("validator")
        return {**next_state, "claim_failures": []}

    def fake_composer(next_state):
        calls.append("composer")
        return {**next_state, "itinerary_draft": "Draft itinerary."}

    def fake_formatter(next_state):
        calls.append("formatter")
        return {
            **next_state,
            "final_geojson": {"type": "FeatureCollection", "features": []},
            "final_itinerary": "Draft itinerary.",
        }

    result = run_confirmed_destination_pipeline(
        state,
        route_runner=fake_route,
        validator_runner=fake_validator,
        composer_runner=fake_composer,
        formatter_runner=fake_formatter,
    )

    assert calls == ["route", "validator", "composer", "formatter"]
    assert result["final_itinerary"] == "Draft itinerary."


def test_pipeline_stops_for_n5_reprompt() -> None:
    state = {"user_confirmed": True}
    calls = []

    def fake_route(next_state):
        calls.append("route")
        return {**next_state, "route": {"total_distance_meters": 1000}}

    def fake_validator(next_state):
        calls.append("validator")
        return {
            **next_state,
            "user_confirmed": False,
            "validated_candidates": [{"name": "Remaining"}],
            "validated_destination": {"name": "Remaining"},
            "claim_failures": [
                {"field": "timeline", "issue": "Bad route.", "severity": "error"}
            ],
        }

    def fake_composer(next_state):
        calls.append("composer")
        return next_state

    result = run_confirmed_destination_pipeline(
        state,
        route_runner=fake_route,
        validator_runner=fake_validator,
        composer_runner=fake_composer,
    )

    assert calls == ["route", "validator"]
    assert result["validated_destination"] == {"name": "Remaining"}
