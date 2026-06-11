from app import (
    MAX_AUTO_RESUMES,
    advance_graph,
    destination_empty_message,
    destination_summary,
    final_geojson_center,
    food_availability_rows,
    format_duration,
    format_km,
    _first_query_param,
    is_completed_plan_snapshot,
    plan_history_caption,
    plan_history_summary,
    plan_history_title,
    timeline_rows,
    validate_signup_fields,
)
from persistence.database import PlanHistoryItem


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


def test_plan_history_title_uses_start_and_destinations() -> None:
    title = plan_history_title(
        {
            "constraints": {"start_location": "Kochi"},
            "selected_destinations": [
                {"name": "Fort Kochi"},
                {"name": "Mattancherry Palace"},
                {"name": "Marine Drive"},
            ],
        }
    )

    assert title == "Kochi to Fort Kochi, Mattancherry Palace + 1 more"


def test_plan_history_summary_keeps_sidebar_safe_metadata() -> None:
    summary = plan_history_summary(
        {
            "constraints": {
                "start_location": "Kochi",
                "duration_hours": 8,
                "vehicle": "car",
                "interests": ["heritage"],
            },
            "selected_destinations": [{"name": "Fort Kochi"}],
            "route": {
                "total_distance_meters": 24000,
                "planned_duration_seconds": 14400,
            },
        }
    )

    assert summary == {
        "start_location": "Kochi",
        "duration_hours": 8,
        "vehicle": "car",
        "interests": ["heritage"],
        "destinations": ["Fort Kochi"],
        "total_distance_meters": 24000,
        "planned_duration_seconds": 14400,
    }


def test_plan_history_caption_formats_completed_plan_metadata() -> None:
    caption = plan_history_caption(
        PlanHistoryItem(
            thread_id="thread-1",
            title="Kochi to Fort Kochi",
            plan_summary={
                "destinations": ["Fort Kochi", "Mattancherry Palace"],
                "total_distance_meters": 24000,
                "planned_duration_seconds": 14400,
            },
            completed_at="2026-06-11 16:00",
        )
    )

    assert caption == "2026-06-11 16:00 · 2 stops · 24.0 km · 4 hr"


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


def test_validate_signup_fields_accepts_valid_values() -> None:
    assert validate_signup_fields(
        "alice-1",
        "alice@example.com",
        "strong-pass",
        "strong-pass",
    ) == []


def test_validate_signup_fields_reports_invalid_values() -> None:
    errors = validate_signup_fields("a!", "alice", "short", "different")

    assert "Username must be at least 3 characters." in errors
    assert "Username can only contain letters, numbers, hyphens, and underscores." in errors
    assert "Enter a valid email address." in errors
    assert "Password must be at least 8 characters." in errors
    assert "Passwords do not match." in errors


def test_first_query_param_accepts_streamlit_string_or_list_values() -> None:
    assert _first_query_param("token") == "token"
    assert _first_query_param(["token", "other"]) == "token"
    assert _first_query_param([]) == ""
    assert _first_query_param(None) == ""


class FakeSnapshot:
    def __init__(self, values: dict, next_nodes: tuple) -> None:
        self.values = values
        self.next = next_nodes


class FakeGraph:
    """Plays back a queue of snapshots; each invoke(None) consumes one."""

    def __init__(self, snapshots: list[FakeSnapshot]) -> None:
        self.snapshots = list(snapshots)
        self.resumes = 0

    def get_state(self, config: dict) -> FakeSnapshot:
        return self.snapshots[0]

    def invoke(self, graph_input, config: dict) -> None:
        assert graph_input is None
        self.resumes += 1
        self.snapshots.pop(0)


def test_advance_graph_resumes_confirmed_n4_pauses_until_parked_at_n8() -> None:
    graph = FakeGraph(
        [
            FakeSnapshot({"user_confirmed": True}, ("n4_route",)),
            FakeSnapshot({"user_confirmed": True}, ("n4_route",)),  # N5 replan re-entry
            FakeSnapshot({"user_confirmed": True}, ("n8_editor",)),
        ]
    )

    snapshot = advance_graph(graph, {})

    assert graph.resumes == 2
    assert snapshot.next == ("n8_editor",)


def test_is_completed_plan_snapshot_requires_n8_interrupt_and_final_output() -> None:
    assert is_completed_plan_snapshot(
        FakeSnapshot(
            {
                "final_itinerary": "Plan",
                "final_geojson": {"type": "FeatureCollection", "features": []},
            },
            ("n8_editor",),
        )
    )
    assert not is_completed_plan_snapshot(
        FakeSnapshot({"final_itinerary": "Plan", "final_geojson": {}}, ("n8_editor",))
    )
    assert not is_completed_plan_snapshot(
        FakeSnapshot(
            {
                "final_itinerary": "Plan",
                "final_geojson": {"type": "FeatureCollection", "features": []},
            },
            (),
        )
    )


def test_advance_graph_stops_at_unconfirmed_n4_pause_for_the_gallery() -> None:
    graph = FakeGraph([FakeSnapshot({"user_confirmed": False}, ("n4_route",))])

    snapshot = advance_graph(graph, {})

    assert graph.resumes == 0
    assert snapshot.next == ("n4_route",)


def test_advance_graph_backstop_caps_resume_attempts() -> None:
    class StuckGraph(FakeGraph):
        def invoke(self, graph_input, config: dict) -> None:
            self.resumes += 1  # snapshot never changes

    graph = StuckGraph([FakeSnapshot({"user_confirmed": True}, ("n4_route",))])

    snapshot = advance_graph(graph, {})

    assert graph.resumes == MAX_AUTO_RESUMES
    assert snapshot.next == ("n4_route",)
