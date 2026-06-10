from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from graph.state import TripState
from tools.vertex import REASONING_GEMINI_MODEL, get_chat_model


MAX_DURATION_HOURS = 14.0  # Short-trip router bound; longer trips route to future_multiday.
DEPARTURE_TIME_PATTERN = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")

EDIT_FAILURE_NOTICE = "I couldn't apply that edit — try rephrasing it."
DURATION_CHANGE_WARNING = (
    "Heads up — stops were validated for your original window; "
    "if something no longer fits, I'll drop it and tell you."
)

SYSTEM_PROMPT = """You are N8, the Picnix plan editor.

The user has a finished day-trip itinerary and is asking for a change in natural language.
Decide the new ordered list of stops and any timing changes, then return JSON matching the
response schema.

Rules:
- You may only use place IDs from the lists provided. If the user asks for a place or
  category not in the lists, do not invent one — put it in `unfulfilled` with reason
  "not in the validated pool for this trip".
- Keep at least 1 and at most `max_destinations` IDs. If the user asks to remove every
  stop, keep the list unchanged and add an `unfulfilled` entry suggesting they start a
  new plan.
- Preserve the existing order of stops you are not changing.
- If the instruction is purely a timing change, return `updated_place_ids` identical to
  the current plan.
- Set `departure_time` ("HH:MM") only if the user asked to change it, else null.
- Set `duration_hours` (number) only if the user asked to change it, else null.
- `edit_summary` is one sentence describing what was applied.
"""

EDITOR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "updated_place_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ordered place IDs for the edited plan; subset of the provided IDs only.",
        },
        "departure_time": {
            "type": "string",
            "nullable": True,
            "description": "HH:MM, only if the user asked to change it.",
        },
        "duration_hours": {
            "type": "number",
            "nullable": True,
            "description": "Only if the user asked to change it.",
        },
        "edit_summary": {
            "type": "string",
            "description": "One sentence: what was applied.",
        },
        "unfulfilled": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "request": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["request", "reason"],
            },
            "description": "Requests that could not be applied.",
        },
    },
    "required": ["updated_place_ids", "edit_summary", "unfulfilled"],
}

# Mirrors the artifact reset on N5's CS4 replan path (`_error_updates` in n5_validator.py),
# so N4 rebuilds the route from scratch after every edit.
ROUTE_ARTIFACT_RESETS: dict[str, Any] = {
    "route": {},
    "food_stops": [],
    "food_availability": [],
    "timeline": [],
    "itinerary_draft": "",
    "final_geojson": {},
    "final_itinerary": "",
    "claim_failures": [],
    "removal_notice": "",
}


class PlanEditError(RuntimeError):
    pass


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
        if character != "{":
            continue
        try:
            _, end = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        return stripped[index : index + end]
    return stripped


def _parse_editor_payload(content: Any) -> dict[str, Any]:
    try:
        payload = json.loads(_extract_json_text(_content_to_text(content)))
    except json.JSONDecodeError as exc:
        raise PlanEditError("N8 returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise PlanEditError("N8 JSON response must be an object.")
    if not isinstance(payload.get("updated_place_ids"), list):
        raise PlanEditError("N8 response missing updated_place_ids list.")
    return payload


def _place_summary(place: dict[str, Any]) -> dict[str, Any]:
    return {
        "place_id": place.get("place_id", ""),
        "name": place.get("name", ""),
        "primary_type": place.get("primary_type", ""),
    }


def _editor_input(state: TripState) -> dict[str, Any]:
    selected = list(state.get("selected_destinations", []))
    selected_ids = {place.get("place_id") for place in selected}
    alternatives = [
        candidate
        for candidate in state.get("validated_candidates", [])
        if candidate.get("place_id") not in selected_ids
    ]
    constraints = state.get("constraints", {})
    return {
        "edit_instruction": state.get("edit_instruction", ""),
        "current_plan": [_place_summary(place) for place in selected],
        "available_alternatives": [_place_summary(place) for place in alternatives],
        "departure_time": constraints.get("departure_time", ""),
        "duration_hours": constraints.get("duration_hours"),
        "max_destinations": int(state.get("max_destinations", 3)),
    }


def candidate_universe(state: TripState) -> dict[str, dict[str, Any]]:
    """Closed set of every destination the edited plan may contain, keyed by place_id."""
    universe = {d["place_id"]: d for d in state.get("selected_destinations", []) if d.get("place_id")}
    universe.update(
        {c["place_id"]: c for c in state.get("validated_candidates", []) if c.get("place_id")}
    )
    return universe


def _unfulfilled_entries(llm_result: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for item in llm_result.get("unfulfilled", []):
        if not isinstance(item, dict):
            continue
        request = str(item.get("request", "")).strip()
        reason = str(item.get("reason", "")).strip()
        if request or reason:
            entries.append({"request": request, "reason": reason})
    return entries


def _valid_departure_time(value: Any) -> str:
    candidate = str(value).strip() if value is not None else ""
    return candidate if DEPARTURE_TIME_PATTERN.match(candidate) else ""


def _valid_duration_hours(value: Any) -> float | None:
    if value is None:
        return None
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if 0 < duration <= MAX_DURATION_HOURS:
        return duration
    return None


def apply_edit_result(llm_result: dict[str, Any], state: TripState) -> dict[str, Any]:
    """Enforce N8's LLM output against the closed candidate universe and return state updates.

    Pure function: never trusts the LLM. Unknown IDs are dropped, empty/oversized results
    fall back to the unchanged plan, timing values are validated before touching
    `constraints`, and the route artifacts are reset so N4 rebuilds from scratch.
    """
    universe = candidate_universe(state)
    current = list(state.get("selected_destinations", []))
    max_destinations = int(state.get("max_destinations", 3))

    seen: set[str] = set()
    survivors: list[dict[str, Any]] = []
    for place_id in llm_result.get("updated_place_ids", []):
        key = str(place_id)
        if key in universe and key not in seen:
            survivors.append(universe[key])
            seen.add(key)

    notice_parts: list[str] = []
    if not survivors:
        survivors = current
        notice_parts.append(
            "I couldn't match that edit to your validated places, so the plan is unchanged."
        )
    elif len(survivors) > max_destinations:
        survivors = current
        notice_parts.append(
            f"That edit needs more than {max_destinations} stops, so the plan is unchanged."
        )

    summary = str(llm_result.get("edit_summary", "")).strip()
    if summary:
        notice_parts.insert(0, summary)

    constraints = dict(state.get("constraints", {}))
    departure_time = _valid_departure_time(llm_result.get("departure_time"))
    if departure_time:
        constraints["departure_time"] = departure_time
    elif llm_result.get("departure_time") is not None:
        notice_parts.append("The new departure time wasn't a valid HH:MM, so I kept the old one.")

    duration_hours = _valid_duration_hours(llm_result.get("duration_hours"))
    if duration_hours is not None:
        constraints["duration_hours"] = duration_hours
        notice_parts.append(DURATION_CHANGE_WARNING)
    elif llm_result.get("duration_hours") is not None:
        notice_parts.append(
            f"The new trip length must be between 0 and {MAX_DURATION_HOURS:g} hours, so I kept the old one."
        )

    unfulfilled = _unfulfilled_entries(llm_result)
    notice_parts.extend(
        f"Couldn't do \"{entry['request']}\" — {entry['reason']}"
        for entry in unfulfilled
        if entry["reason"]
    )

    history_entry = {
        "instruction": str(state.get("edit_instruction", "")),
        "timestamp": datetime.now().isoformat(),
        "resulting_destinations": [str(place.get("name", "")) for place in survivors],
        "unfulfilled": unfulfilled,
    }

    return {
        "selected_destinations": survivors,
        "constraints": constraints,
        "edit_history": [*state.get("edit_history", []), history_entry],
        "edit_notice": " ".join(notice_parts).strip(),
        "edit_instruction": "",
        "user_confirmed": True,
        "route_attempt_count": 0,
        **ROUTE_ARTIFACT_RESETS,
    }


def _failure_updates(state: TripState) -> dict[str, Any]:
    history_entry = {
        "instruction": str(state.get("edit_instruction", "")),
        "timestamp": datetime.now().isoformat(),
        "resulting_destinations": [
            str(place.get("name", "")) for place in state.get("selected_destinations", [])
        ],
        "unfulfilled": [
            {"request": str(state.get("edit_instruction", "")), "reason": "editor error"}
        ],
    }
    return {
        "selected_destinations": list(state.get("selected_destinations", [])),
        "edit_history": [*state.get("edit_history", []), history_entry],
        "edit_notice": EDIT_FAILURE_NOTICE,
        "edit_instruction": "",
        "user_confirmed": True,
        "route_attempt_count": 0,
        **ROUTE_ARTIFACT_RESETS,
    }


def edit_plan(state: TripState, *, model: Any | None = None) -> dict[str, Any]:
    """Apply the user's natural-language edit to the finished plan and hand control back to N4.

    Reads from state:  edit_instruction, selected_destinations, validated_candidates,
                       constraints, max_destinations
    Writes to state:   selected_destinations, constraints (timing fields only),
                       edit_history (appended), edit_notice, edit_instruction (cleared),
                       user_confirmed=True, route_attempt_count=0, removal_notice="",
                       route/timeline/food_stops/food_availability/claim_failures (reset)

    One LLM call decides the new stop list as place IDs from a closed universe
    (current stops + validated candidates); Python enforcement maps IDs back to the
    real destination dicts and never lets the LLM author a destination object. On any
    LLM failure the plan is left unchanged and N4 harmlessly rebuilds the same route.
    """
    try:
        chat_model = model or get_chat_model(
            model=REASONING_GEMINI_MODEL,
            temperature=1.0,
            response_mime_type="application/json",
            response_schema=EDITOR_RESPONSE_SCHEMA,
        )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(_editor_input(state), sort_keys=True)),
        ]
        response = chat_model.invoke(messages)
        payload = _parse_editor_payload(response.content)
    except Exception:
        return _failure_updates(state)

    return apply_edit_result(payload, state)
