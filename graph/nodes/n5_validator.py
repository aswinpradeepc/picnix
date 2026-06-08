from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from graph.state import TripState
from tools.vertex import REASONING_GEMINI_MODEL, get_chat_model


GRACEFUL_FAILURE_MESSAGE = (
    "Couldn't build a workable plan for any nearby destination - try again with different preferences."
)

SYSTEM_PROMPT = """You are N5, the Picnix structured output validator.

Validate the supplied N4 route output semantically. Python has already checked required
fields, time ordering, route shape, explicit food coverage, and coordinate ranges.

Look only for semantic inconsistencies that Python cannot reliably catch:
- implausibly short or long dwell time at the destination
- remote early-morning destinations with no food guidance
- food availability entries that contradict the destination type
- route or timeline decisions that conflict with the user's constraints

Return only valid JSON as a list of objects:
[
  {"field": "timeline", "issue": "short description", "severity": "warning"}
]

Use severity "error" only when the plan should not be shown to the user. Use "warning"
when the plan is still usable and N6 can mention or avoid the issue.
Return [] when there are no semantic issues.
"""

MEAL_KEYWORDS = {
    "breakfast": {"breakfast"},
    "lunch": {"lunch"},
    "dinner": {"dinner", "supper"},
}
VALID_SEVERITIES = {"warning", "error"}


class StructuredOutputValidationError(RuntimeError):
    pass


def _failure(field: str, issue: str, severity: str = "error") -> dict[str, str]:
    return {"field": field, "issue": issue, "severity": severity}


def _has_error(failures: list[dict[str, str]]) -> bool:
    return any(failure.get("severity") == "error" for failure in failures)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content)


def _strip_fenced_json(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_text(content: str) -> str:
    stripped = _strip_fenced_json(content)
    decoder = json.JSONDecoder()
    for index, character in enumerate(stripped):
        if character not in "[{":
            continue
        try:
            _, end = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        return stripped[index : index + end]
    return stripped


def _parse_semantic_failures(content: Any) -> list[dict[str, str]]:
    try:
        payload = json.loads(_extract_json_text(_content_to_text(content)))
    except json.JSONDecodeError as exc:
        raise StructuredOutputValidationError("N5 semantic pass returned invalid JSON.") from exc

    if isinstance(payload, dict):
        payload = (
            payload.get("issues")
            or payload.get("claim_failures")
            or payload.get("failures")
            or []
        )
    if not isinstance(payload, list):
        raise StructuredOutputValidationError("N5 semantic JSON response must be a list.")

    failures: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise StructuredOutputValidationError("N5 semantic issue entries must be objects.")

        field = str(item.get("field", "semantic")).strip() or "semantic"
        issue = str(item.get("issue", "")).strip()
        if not issue:
            continue

        severity = str(item.get("severity", "warning")).strip().lower()
        if severity not in VALID_SEVERITIES:
            severity = "warning"
        failures.append(_failure(field, issue, severity))

    return failures


def _parse_hhmm(value: Any) -> int | None:
    parts = str(value or "").strip().split(":", maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def _relative_minutes(value: Any, anchor: int | None) -> int | None:
    minutes = _parse_hhmm(value)
    if minutes is None:
        return None
    if anchor is not None and minutes < anchor:
        return minutes + 24 * 60
    return minutes


def _timeline_with_minutes(
    timeline: list[dict[str, Any]],
    *,
    anchor: int | None,
) -> tuple[list[tuple[int, dict[str, Any]]], list[dict[str, str]]]:
    entries: list[tuple[int, dict[str, Any]]] = []
    failures: list[dict[str, str]] = []
    for index, entry in enumerate(timeline):
        minutes = _relative_minutes(entry.get("time"), anchor)
        if minutes is None:
            failures.append(
                _failure(
                    f"timeline[{index}].time",
                    f"Timeline entry {index} must use HH:MM time.",
                )
            )
            continue
        entries.append((minutes, entry))
    return entries, failures


def _check_timeline_completeness(
    timeline: list[dict[str, Any]],
) -> list[dict[str, str]]:
    if not timeline:
        return [_failure("timeline", "Timeline must contain at least one entry.")]

    failures: list[dict[str, str]] = []
    required_fields = ("time", "label", "coords", "type", "notes")
    for index, entry in enumerate(timeline):
        if not isinstance(entry, dict):
            failures.append(_failure(f"timeline[{index}]", "Timeline entry must be an object."))
            continue
        for field in required_fields:
            value = entry.get(field)
            if value == "" or value is None or value == {}:
                failures.append(
                    _failure(
                        f"timeline[{index}].{field}",
                        f"Timeline entry {index} is missing {field}.",
                    )
                )
    return failures


def _check_timeline_ordering(
    state: TripState,
    timeline: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    anchor = _parse_hhmm(state.get("constraints", {}).get("departure_time"))
    entries, failures = _timeline_with_minutes(timeline, anchor=anchor)
    if failures:
        return failures, {}

    minutes = [entry_minutes for entry_minutes, _ in entries]
    if minutes == sorted(minutes):
        return [], {}

    ordered_timeline = [
        entry for _, entry in sorted(entries, key=lambda item: item[0])
    ]
    return [
        _failure(
            "timeline",
            "Timeline entries were out of chronological order and were reordered.",
            "warning",
        )
    ], {"timeline": ordered_timeline}


def _check_time_arithmetic(
    state: TripState,
    timeline: list[dict[str, Any]],
) -> list[dict[str, str]]:
    anchor = _parse_hhmm(state.get("constraints", {}).get("departure_time"))
    entries, failures = _timeline_with_minutes(timeline, anchor=anchor)
    if failures:
        return failures

    by_type = {str(entry.get("type")): (minutes, entry) for minutes, entry in entries}
    required_types = ("start", "destination", "return_departure", "return")
    for entry_type in required_types:
        if entry_type not in by_type:
            return [_failure("timeline", f"Timeline is missing a {entry_type} entry.")]

    start_minutes = by_type["start"][0]
    destination_minutes = by_type["destination"][0]
    return_departure_minutes = by_type["return_departure"][0]
    return_minutes = by_type["return"][0]
    if start_minutes <= destination_minutes <= return_departure_minutes <= return_minutes:
        return []
    return [
        _failure(
            "timeline",
            "Timeline must satisfy departure <= destination arrival <= destination departure <= return arrival.",
        )
    ]


def _check_route_shape(route: dict[str, Any]) -> list[dict[str, str]]:
    coordinates = (
        route.get("geojson", {})
        .get("geometry", {})
        .get("coordinates")
    )
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return [
            _failure(
                "route.geojson.geometry.coordinates",
                "Route LineString must contain at least two coordinates.",
            )
        ]
    return []


def _state_text_for_meals(state: TripState) -> str:
    parts: list[str] = []
    for message in state.get("raw_messages", []):
        parts.append(str(message.get("content", "")))
    constraints = state.get("constraints", {})
    for value in constraints.values():
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return " ".join(parts).lower()


def _explicit_meals(state: TripState) -> list[str]:
    text = _state_text_for_meals(state)
    meals: list[str] = []
    for meal, keywords in MEAL_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            meals.append(meal)
    return meals


def _check_food_coverage(state: TripState) -> list[dict[str, str]]:
    requested_meals = _explicit_meals(state)
    if not requested_meals:
        return []

    covered_meals = {
        str(entry.get("meal", "")).strip().lower()
        for entry in state.get("food_availability", [])
        if isinstance(entry, dict)
    }
    failures: list[dict[str, str]] = []
    for meal in requested_meals:
        if meal not in covered_meals:
            failures.append(
                _failure(
                    "food_availability",
                    f"Explicit {meal} request is missing from food_availability.",
                )
            )
    return failures


def _iter_coords(value: Any, prefix: str) -> list[tuple[str, Any]]:
    coords: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        if "coords" in value:
            coords.append((f"{prefix}.coords" if prefix else "coords", value.get("coords")))
        for key, child in value.items():
            if key == "coords":
                continue
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            coords.extend(_iter_coords(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            coords.extend(_iter_coords(child, f"{prefix}[{index}]"))
    return coords


def _valid_coords(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        lat = float(value["lat"])
        lng = float(value["lng"])
    except (KeyError, TypeError, ValueError):
        return False
    return -90 <= lat <= 90 and -180 <= lng <= 180


def _check_coords_validity(state: TripState) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for field, coords in _iter_coords(
        {
            "timeline": state.get("timeline", []),
            "food_availability": state.get("food_availability", []),
            "food_stops": state.get("food_stops", []),
            "validated_destination": state.get("validated_destination", {}),
            "route": state.get("route", {}),
        },
        "",
    ):
        if not _valid_coords(coords):
            failures.append(
                _failure(
                    field,
                    "Coordinates must have lat in [-90, 90] and lng in [-180, 180].",
                )
            )
    return failures


def _run_python_checks(state: TripState) -> tuple[list[dict[str, str]], dict[str, Any]]:
    failures: list[dict[str, str]] = []
    updates: dict[str, Any] = {}

    timeline = list(state.get("timeline", []))
    for check in (
        lambda: (_check_timeline_completeness(timeline), {}),
        lambda: _check_timeline_ordering(state, timeline),
    ):
        check_failures, check_updates = check()
        failures.extend(check_failures)
        updates.update(check_updates)
        timeline = list(updates.get("timeline", timeline))
        if _has_error(check_failures):
            return failures, updates

    check_sequence = (
        lambda current_state: _check_time_arithmetic(current_state, timeline),
        lambda current_state: _check_route_shape(current_state.get("route", {})),
        _check_food_coverage,
        _check_coords_validity,
    )
    current_state = {**state, **updates}
    for check in check_sequence:
        check_failures = check(current_state)
        failures.extend(check_failures)
        if _has_error(check_failures):
            return failures, updates

    return failures, updates


def _semantic_summary(state: TripState) -> dict[str, Any]:
    destination = state.get("validated_destination", {})
    return {
        "timeline": state.get("timeline", []),
        "food_availability": state.get("food_availability", []),
        "validated_destination": {
            "name": destination.get("name", ""),
            "place_id": destination.get("place_id", ""),
            "types": destination.get("types", []),
            "primary_type": destination.get("primary_type", ""),
            "coords": destination.get("coords", {}),
        },
        "constraints": state.get("constraints", {}),
        "route": {
            "total_distance_meters": state.get("route", {}).get("total_distance_meters"),
            "travel_duration_seconds": state.get("route", {}).get("travel_duration_seconds"),
            "planned_duration_seconds": state.get("route", {}).get("planned_duration_seconds"),
            "legs": state.get("route", {}).get("legs", []),
        },
    }


def _run_semantic_pass(
    state: TripState,
    *,
    model: Any | None,
) -> list[dict[str, str]]:
    chat_model = model or get_chat_model(
        model=REASONING_GEMINI_MODEL,
        temperature=1.0,
        response_mime_type="application/json",
    )
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(_semantic_summary(state), sort_keys=True)),
    ]
    response = chat_model.invoke(messages)
    return _parse_semantic_failures(response.content)


def _same_destination(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_place_id = str(first.get("place_id", "")).strip()
    second_place_id = str(second.get("place_id", "")).strip()
    if first_place_id and second_place_id:
        return first_place_id == second_place_id
    first_name = str(first.get("name", "")).strip().lower()
    second_name = str(second.get("name", "")).strip().lower()
    return bool(first_name and second_name and first_name == second_name)


def _remaining_candidates_after_rejection(state: TripState) -> list[dict[str, Any]]:
    current_destination = dict(state.get("validated_destination", {}))
    candidates = list(state.get("validated_candidates", []))
    remaining = [
        candidate
        for candidate in candidates
        if not _same_destination(candidate, current_destination)
    ]
    if len(remaining) != len(candidates):
        return remaining

    presented_index = int(state.get("presented_candidate_index", 0))
    if 0 <= presented_index < len(candidates):
        return [
            candidate
            for index, candidate in enumerate(candidates)
            if index != presented_index
        ]
    return candidates


def _error_updates(
    state: TripState,
    failures: list[dict[str, str]],
) -> dict[str, Any]:
    remaining_candidates = _remaining_candidates_after_rejection(state)
    updates: dict[str, Any] = {
        "claim_failures": failures,
        "validated_candidates": remaining_candidates,
        "presented_candidate_index": 0,
        "validated_destination": remaining_candidates[0] if remaining_candidates else {},
        "user_confirmed": False,
        "route_attempt_count": int(state.get("route_attempt_count", 0)) + 1,
        "route": {},
        "food_stops": [],
        "food_availability": [],
        "timeline": [],
        "itinerary_draft": "",
        "final_geojson": {},
        "final_itinerary": "",
    }
    if not remaining_candidates:
        updates["final_itinerary"] = GRACEFUL_FAILURE_MESSAGE
    return updates


def validate_structured_output(
    state: TripState,
    *,
    model: Any | None = None,
) -> dict[str, Any]:
    """Read N4 `route`, `timeline`, and food decisions, then write `claim_failures` plus filtered destination state when validation finds an error."""
    python_failures, python_updates = _run_python_checks(state)
    if _has_error(python_failures):
        return _error_updates({**state, **python_updates}, python_failures)

    checked_state = {**state, **python_updates}
    semantic_failures = _run_semantic_pass(checked_state, model=model)
    failures = [*python_failures, *semantic_failures]
    if _has_error(failures):
        return _error_updates(checked_state, failures)

    return {
        **python_updates,
        "claim_failures": failures,
    }
