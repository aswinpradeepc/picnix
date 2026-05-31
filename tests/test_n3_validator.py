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
    ) -> None:
        self.business_status = business_status
        self.open_for_window = open_for_window
        self.duration_seconds = duration_seconds
        self.distance_meters = distance_meters

    def get_place_details(self, place_id, *, settings=None):
        return {
            "place_id": place_id,
            "name": place_id,
            "business_status": self.business_status,
            "regular_opening_hours": {},
        }

    def validate_place_open_for_window(self, details, window_start, window_end):
        assert window_start == datetime(2026, 5, 31, 7, 0)
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
        "validation_failures": [],
    }


def test_validate_destination_accepts_open_reachable_candidate() -> None:
    result = validate_destination(
        base_state(),
        gmaps_client=FakeGMaps(),
        trip_start=datetime(2026, 5, 31, 7, 0),
    )

    assert result["validated_destination"]["place_id"] == "place-1"
    assert result["validated_destination"]["travel_time_seconds"] == 1800
    assert result["validated_destination"]["distance_meters"] == 40000
    assert result["candidate_index"] == 0
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


def test_validate_destination_adds_known_restriction_note_without_rejecting() -> None:
    result = validate_destination(
        base_state(candidate_name="Anamudi Peak"),
        gmaps_client=FakeGMaps(),
        trip_start=datetime(2026, 5, 31, 7, 0),
    )

    assert result["validated_destination"]["notes"] == [
        "permit required, check DFO office"
    ]


def test_validate_destination_reports_no_remaining_candidates() -> None:
    state = base_state()
    state["candidate_index"] = 3

    result = validate_destination(
        state,
        gmaps_client=FakeGMaps(),
        trip_start=datetime(2026, 5, 31, 7, 0),
    )

    assert result["validation_failures"] == ["No destination candidates remain."]
