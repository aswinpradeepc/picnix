from datetime import datetime

from graph.nodes.time_utils import (
    infer_departure_time,
    normalize_departure_time,
    trip_start_from_constraints,
)


def test_normalize_departure_time_accepts_common_time_forms() -> None:
    assert normalize_departure_time("7am", duration_hours=8) == "07:00"
    assert normalize_departure_time("5:30 pm", duration_hours=4) == "17:30"
    assert normalize_departure_time("evening", duration_hours=4) == "17:00"


def test_departure_time_inference_uses_trip_context() -> None:
    assert infer_departure_time(10, ["nature"]) == "06:00"
    assert infer_departure_time(8, ["long_rides"]) == "08:00"
    assert infer_departure_time(4, ["food"]) == "17:00"
    assert infer_departure_time(5, ["culture"]) == "15:00"


def test_trip_start_from_constraints_uses_next_occurrence_of_departure_time() -> None:
    result = trip_start_from_constraints(
        {"duration_hours": 6, "departure_time": "09:30", "interests": []},
        now=datetime(2026, 6, 6, 8, 0),
    )

    assert result == datetime(2026, 6, 6, 9, 30)


def test_trip_start_from_constraints_rolls_elapsed_departure_to_next_day() -> None:
    result = trip_start_from_constraints(
        {"duration_hours": 6, "departure_time": "09:30", "interests": []},
        now=datetime(2026, 6, 6, 10, 0),
    )

    assert result == datetime(2026, 6, 7, 9, 30)
