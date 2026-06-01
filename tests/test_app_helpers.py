from app import destination_empty_message, destination_summary, format_duration, format_km


def test_format_km_formats_meters() -> None:
    assert format_km(17047) == "17.0 km"


def test_format_duration_formats_seconds() -> None:
    assert format_duration(1869) == "31 min"
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
