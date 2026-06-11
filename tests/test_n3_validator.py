from datetime import datetime

from graph.nodes.n3_validator import validate_destination


class FakeGMaps:
    def __init__(
        self,
        *,
        business_status="OPERATIONAL",
        open_for_window=True,
        duration_seconds=1800,
        distance_meters=40000,
        expected_window_start=datetime(2026, 5, 31, 7, 0),
    ) -> None:
        self.business_status = business_status
        self.open_for_window = open_for_window
        self.duration_seconds = duration_seconds
        self.distance_meters = distance_meters
        self.expected_window_start = expected_window_start

    def get_place_details(self, place_id, *, settings=None):
        return {
            "place_id": place_id,
            "name": place_id,
            "business_status": self.business_status,
            "regular_opening_hours": {},
        }

    def validate_place_open_for_window(self, details, window_start, window_end):
        assert window_start == self.expected_window_start
        return self.open_for_window

    def compute_route(self, *, origin, destination, settings=None):
        assert origin == {"lat": 9.9312, "lng": 76.2673}
        assert destination == {"lat": 10.0, "lng": 76.3}
        return {
            "duration_seconds": self.duration_seconds,
            "distance_meters": self.distance_meters,
            "encoded_polyline": "encoded",
        }


def base_state(candidate_name="Valid Place"):
    return {
        "constraints": {"duration_hours": 8},
        "isochrone_polygon": {
            "properties": {"center": {"lat": 9.9312, "lng": 76.2673}}
        },
        "candidates": [
            {
                "place_id": "place-1",
                "name": candidate_name,
                "coords": {"lat": 10.0, "lng": 76.3},
                "notes": [],
            }
        ],
        "candidate_index": 0,
        "validated_candidates": [],
        "validated_destination": {},
        "validation_failures": [],
    }


def test_validate_destination_accepts_open_reachable_candidate() -> None:
    result = validate_destination(
        base_state(),
        gmaps_client=FakeGMaps(),
        trip_start=datetime(2026, 5, 31, 7, 0),
    )

    assert result["validated_candidates"][0]["place_id"] == "place-1"
    assert result["validated_candidates"][0]["travel_time_seconds"] == 1800
    assert result["validated_candidates"][0]["distance_meters"] == 40000
    assert result["validated_destination"]["place_id"] == "place-1"
    assert result["candidate_index"] == 1
    assert result["validation_failures"] == []


def test_validate_destination_rejects_permanently_closed_candidate() -> None:
    result = validate_destination(
        base_state(),
        gmaps_client=FakeGMaps(business_status="CLOSED_PERMANENTLY"),
        trip_start=datetime(2026, 5, 31, 7, 0),
    )

    assert "validated_destination" not in result
    assert result["candidate_index"] == 1
    assert result["validation_failures"] == [
        "Valid Place rejected: permanently closed"
    ]


def test_validate_destination_rejects_closed_during_trip_window() -> None:
    result = validate_destination(
        base_state(),
        gmaps_client=FakeGMaps(open_for_window=False),
        trip_start=datetime(2026, 5, 31, 7, 0),
    )

    assert result["candidate_index"] == 1
    assert result["validation_failures"] == [
        "Valid Place rejected: closed during trip window"
    ]


def test_validate_destination_rejects_route_that_exceeds_budget() -> None:
    result = validate_destination(
        base_state(),
        gmaps_client=FakeGMaps(duration_seconds=15000),
        trip_start=datetime(2026, 5, 31, 7, 0),
    )

    assert result["candidate_index"] == 1
    assert result["validation_failures"] == [
        "Valid Place rejected: travel time 15000s exceeds allowed 14040s"
    ]


def test_validate_destination_does_not_reject_when_default_known_issue_file_is_empty() -> None:
    result = validate_destination(
        base_state(candidate_name="Anamudi Peak"),
        gmaps_client=FakeGMaps(),
        trip_start=datetime(2026, 5, 31, 7, 0),
    )

    assert result["validated_candidates"][0]["place_id"] == "place-1"
    assert result["candidate_index"] == 1
    assert result["validation_failures"] == []


def test_validate_destination_reads_known_place_issue_from_supplied_markdown(tmp_path) -> None:
    issue_file = tmp_path / "known-place-issues.md"
    issue_file.write_text(
        "\n".join(
            [
                "| Place name | Issue | Action |",
                "|---|---|---|",
                "| Valid Place | Monsoon access issue. | reject |",
            ]
        ),
        encoding="utf-8",
    )

    result = validate_destination(
        base_state(),
        gmaps_client=FakeGMaps(),
        trip_start=datetime(2026, 5, 31, 7, 0),
        known_issues_path=issue_file,
    )

    assert result["validation_failures"] == [
        "Valid Place rejected: known place issue: Monsoon access issue."
    ]


def test_validate_destination_appends_to_existing_validated_queue() -> None:
    state = base_state()
    state["validated_candidates"] = [{"place_id": "existing"}]

    result = validate_destination(
        state,
        gmaps_client=FakeGMaps(),
        trip_start=datetime(2026, 5, 31, 7, 0),
    )

    assert [destination["place_id"] for destination in result["validated_candidates"]] == [
        "existing",
        "place-1",
    ]
    assert result["validated_destination"]["place_id"] == "existing"


def test_validate_destination_reports_no_remaining_candidates() -> None:
    state = base_state()
    state["candidate_index"] = 3

    result = validate_destination(
        state,
        gmaps_client=FakeGMaps(),
        trip_start=datetime(2026, 5, 31, 7, 0),
    )

    assert result["validation_failures"] == ["No destination candidates remain."]
