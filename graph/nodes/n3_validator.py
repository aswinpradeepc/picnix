from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config.settings import SETTINGS, Settings
from graph.nodes.time_utils import trip_start_from_constraints
from graph.state import TripState
from tools import gmaps


KNOWN_PLACE_ISSUES_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "known-place-issues.md"
)


def _max_one_way_seconds(duration_hours: float) -> int:
    return int(max((duration_hours - 2) / 2, 0.5) * 3600)


def _failure(
    state: TripState,
    candidate: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "candidate_index": int(state.get("candidate_index", 0)) + 1,
        "validation_failures": [
            *list(state.get("validation_failures", [])),
            f"{candidate.get('name', 'candidate')} rejected: {reason}",
        ],
    }


def _normalize_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


def load_known_place_issues(path: str | Path = KNOWN_PLACE_ISSUES_PATH) -> list[dict[str, str]]:
    issue_path = Path(path)
    if not issue_path.exists():
        return []

    issues: list[dict[str, str]] = []
    for line in issue_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue

        columns = [column.strip() for column in stripped.strip("|").split("|")]
        if len(columns) < 3 or columns[0].lower() == "place name":
            continue

        place_name, issue, action = columns[:3]
        if not place_name or not issue:
            continue

        issues.append(
            {
                "place_name": place_name,
                "issue": issue,
                "action": (action or "reject").lower(),
            }
        )

    return issues


def _known_issue_for_candidate(
    candidate: dict[str, Any],
    *,
    known_issues_path: str | Path = KNOWN_PLACE_ISSUES_PATH,
) -> dict[str, str] | None:
    candidate_names = {
        _normalize_name(str(candidate.get("name", ""))),
        _normalize_name(str(candidate.get("candidate_name", ""))),
        _normalize_name(str(candidate.get("display_name", ""))),
    }
    candidate_names.discard("")
    for issue in load_known_place_issues(known_issues_path):
        if _normalize_name(issue["place_name"]) in candidate_names:
            return issue
    return None


def _notes_for_candidate(
    candidate: dict[str, Any],
    *,
    known_issues_path: str | Path = KNOWN_PLACE_ISSUES_PATH,
) -> list[str]:
    notes = list(candidate.get("notes", []))
    issue = _known_issue_for_candidate(candidate, known_issues_path=known_issues_path)
    if issue and issue["action"] == "warn" and issue["issue"] not in notes:
        notes.append(issue["issue"])
    return notes


def validate_destination(
    state: TripState,
    *,
    settings: Settings = SETTINGS,
    gmaps_client: Any = gmaps,
    trip_start: datetime | None = None,
    known_issues_path: str | Path = KNOWN_PLACE_ISSUES_PATH,
) -> dict[str, Any]:
    """Read the current candidate and validation context, then write either `validated_destination` or the next `candidate_index` with a failure reason."""
    candidates = list(state.get("candidates", []))
    candidate_index = int(state.get("candidate_index", 0))
    if candidate_index >= len(candidates):
        return {
            "validation_failures": [
                *list(state.get("validation_failures", [])),
                "No destination candidates remain.",
            ]
        }

    candidate = candidates[candidate_index]
    details = gmaps_client.get_place_details(candidate["place_id"], settings=settings)
    if details.get("business_status") == "CLOSED_PERMANENTLY":
        return _failure(state, candidate, "permanently closed")

    duration_hours = float(state["constraints"]["duration_hours"])
    window_start = trip_start or trip_start_from_constraints(state["constraints"])
    window_end = window_start + timedelta(hours=duration_hours)
    if not gmaps_client.validate_place_open_for_window(details, window_start, window_end):
        return _failure(state, candidate, "closed during trip window")

    candidate_with_details = {
        **candidate,
        **details,
        "candidate_name": candidate.get("name", ""),
        "name": details.get("name") or candidate.get("name", ""),
    }
    known_issue = _known_issue_for_candidate(
        candidate_with_details,
        known_issues_path=known_issues_path,
    )
    if known_issue and known_issue["action"] == "reject":
        return _failure(state, candidate, f"known place issue: {known_issue['issue']}")

    center = state["isochrone_polygon"]["properties"]["center"]
    route = gmaps_client.compute_route(
        origin=center,
        destination=candidate["coords"],
        settings=settings,
    )
    max_allowed = int(_max_one_way_seconds(duration_hours) * 1.3)
    travel_time = int(route.get("duration_seconds", 0))
    if travel_time > max_allowed:
        return _failure(
            state,
            candidate,
            f"travel time {travel_time}s exceeds allowed {max_allowed}s",
        )

    validated_destination = {
        **candidate,
        **details,
        "coords": candidate["coords"],
        "travel_time_seconds": travel_time,
        "distance_meters": route.get("distance_meters", 0),
        "route_preview": route,
        "notes": _notes_for_candidate(
            candidate_with_details,
            known_issues_path=known_issues_path,
        ),
    }
    validated_candidates = [
        *list(state.get("validated_candidates", [])),
        validated_destination,
    ]
    presented_index = int(state.get("presented_candidate_index", 0))
    return {
        "validated_candidates": validated_candidates,
        "validated_destination": validated_candidates[presented_index]
        if presented_index < len(validated_candidates)
        else validated_candidates[0],
        "validation_failures": list(state.get("validation_failures", [])),
        "candidate_index": candidate_index + 1,
    }
