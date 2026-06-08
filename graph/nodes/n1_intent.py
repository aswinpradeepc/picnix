from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from graph.state import TripState
from graph.nodes.time_utils import normalize_departure_time
from graph.nodes.n2_isochrone import INTEREST_TYPE_MAP
from tools.vertex import REASONING_GEMINI_MODEL, get_chat_model


OPENING_MESSAGE = (
    "Aah, sounds like you need a good day out! Let me help plan it. "
    "Tell me - where are you starting from, how much time do you have, and when do you want to leave?"
)

_INTEREST_KEYS = sorted(INTEREST_TYPE_MAP.keys())


def _build_system_prompt(clarification_round: int) -> str:
    interest_list = ", ".join(_INTEREST_KEYS)
    return f"""You are N1, the Picnix intent collector.

Persona: warm, brief, enthusiastic trip-planning friend.

Collect these constraints:
- start_location: text
- departure_time: 24-hour local time string in HH:MM
- duration_hours: float
- group_size: int
- vehicle: one of bike, car, public, none
- interests: list — valid values: {interest_list}
- budget_feel: one of free, low, medium, splurge

Rules:
- Ask at most 3 question rounds total. Current clarification_round is {clarification_round}.
- Group questions naturally.
- If duration_hours is missing, ask for it explicitly unless clarification_round is already 3.
- If departure_time is missing, ask for it naturally with the other constraints unless clarification_round is already 3.
- If the user is vague and clarification_round is already 3, make reasonable assumptions from the trip mood and state them.
- When enough information is gathered, set done=true and return all constraints.

Ask exactly ONE question per round. Do not chain multiple questions into one message.
The assistant_message must contain only that single question and must match clarification_prompt.question.

When asking a question, always include clarification_prompt so the UI can render the right input control.
Choose input_type for the question:
- multi_select (the user may pick several): use for interests. options must be from: {interest_list}
- single_select (exactly one answer): use for vehicle (bike, car, public, none) and budget_feel (free, low, medium, splurge)
- text (free typing, no preset choices): use for start_location, group_size, departure_time. Leave options empty.
- Always set allow_custom: true.

Return only valid JSON. When asking a question:
{{
  "assistant_message": "the single question you are asking",
  "done": false,
  "asked_question": true,
  "clarification_prompt": {{
    "question": "the single question you are asking",
    "input_type": "single_select",
    "options": ["option1", "option2"],
    "allow_custom": true
  }},
  "constraints": null
}}

When done (all constraints collected):
{{
  "assistant_message": "message to show the user",
  "done": true,
  "asked_question": false,
  "clarification_prompt": null,
  "constraints": {{
    "start_location": "...",
    "departure_time": "09:00",
    "duration_hours": 8.0,
    "group_size": 2,
    "vehicle": "car",
    "interests": ["food"],
    "budget_feel": "medium"
  }}
}}
"""

VALID_VEHICLES = {"bike", "car", "public", "none"}
VALID_BUDGETS = {"free", "low", "medium", "splurge"}
LONG_TRIP_INTERESTS = {"nature", "long_rides", "beach", "waterfall", "hills", "culture"}
SHORT_TRIP_INTERESTS = {"food", "shopping", "movies"}


class IntentCollectionError(RuntimeError):
    pass


def _message_from_dict(message: dict[str, str]) -> BaseMessage:
    role = message.get("role")
    content = message.get("content", "")
    if role == "assistant":
        return AIMessage(content=content)
    if role == "system":
        return SystemMessage(content=content)
    return HumanMessage(content=content)


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


def _parse_payload(content: Any) -> dict[str, Any]:
    try:
        payload = json.loads(_extract_json_text(_content_to_text(content)))
    except json.JSONDecodeError as exc:
        raise IntentCollectionError("N1 returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise IntentCollectionError("N1 JSON response must be an object.")
    return payload


def _normalize_constraints(raw: dict[str, Any]) -> dict[str, Any]:
    vehicle = str(raw.get("vehicle", "none")).strip().lower()
    if vehicle not in VALID_VEHICLES:
        vehicle = "none"

    budget_feel = str(raw.get("budget_feel", "medium")).strip().lower()
    if budget_feel not in VALID_BUDGETS:
        budget_feel = "medium"

    interests = raw.get("interests", [])
    if isinstance(interests, str):
        interests = [interests]
    normalized_interests = [
        str(interest).strip().lower() for interest in interests if str(interest).strip()
    ]
    duration_hours = _normalize_duration_hours(raw.get("duration_hours"), normalized_interests)

    return {
        "start_location": str(raw.get("start_location", "")).strip(),
        "departure_time": normalize_departure_time(
            raw.get("departure_time"),
            duration_hours=duration_hours,
            interests=normalized_interests,
        ),
        "duration_hours": duration_hours,
        "group_size": int(raw.get("group_size", 1)),
        "vehicle": vehicle,
        "interests": normalized_interests,
        "budget_feel": budget_feel,
    }


def _normalize_duration_hours(value: Any, interests: list[str]) -> float:
    try:
        duration_hours = float(value or 0)
    except (TypeError, ValueError):
        duration_hours = 0

    if duration_hours > 0:
        return duration_hours

    normalized_interests = {
        interest.strip().lower().replace("-", "_").replace(" ", "_")
        for interest in interests
    }
    if normalized_interests.intersection(LONG_TRIP_INTERESTS):
        return 8.0
    if normalized_interests.intersection(SHORT_TRIP_INTERESTS):
        return 4.0
    return 6.0


VALID_INPUT_TYPES = {"single_select", "multi_select", "text"}


def _extract_clarification_prompt(payload: dict[str, Any]) -> dict:
    raw = payload.get("clarification_prompt")
    if not isinstance(raw, dict):
        return {}
    question = str(raw.get("question", "")).strip()
    if not question:
        return {}

    options = [str(o).strip() for o in raw.get("options", []) if str(o).strip()]
    input_type = str(raw.get("input_type", "")).strip().lower()
    if input_type not in VALID_INPUT_TYPES:
        # Infer from options: choices imply a select, no choices implies free text.
        input_type = "single_select" if options else "text"

    # Select-type questions are meaningless without choices; fall back to text.
    if input_type in {"single_select", "multi_select"} and not options:
        input_type = "text"

    return {
        "question": question,
        "input_type": input_type,
        "options": options,
        "allow_custom": bool(raw.get("allow_custom", True)),
    }


def collect_intent(state: TripState, *, model: Any | None = None) -> dict[str, Any]:
    """Read `raw_messages` and `clarification_round`, then write updated chat history, clarification_prompt, and constraints when N1 has enough information."""
    raw_messages = list(state.get("raw_messages", []))
    clarification_round = int(state.get("clarification_round", 0))

    if not raw_messages:
        return {
            "raw_messages": [{"role": "assistant", "content": OPENING_MESSAGE}],
            "clarification_round": clarification_round,
            "clarification_prompt": {},
        }

    chat_model = model or get_chat_model(
        model=REASONING_GEMINI_MODEL,
        temperature=1.0,
        response_mime_type="application/json",
    )
    messages = [
        SystemMessage(content=_build_system_prompt(clarification_round)),
        *[_message_from_dict(message) for message in raw_messages],
    ]
    response = chat_model.invoke(messages)
    payload = _parse_payload(response.content)

    assistant_message = str(payload.get("assistant_message", "")).strip()
    if not assistant_message:
        raise IntentCollectionError("N1 response missing assistant_message.")

    done = bool(payload.get("done", False))
    asked_question = bool(payload.get("asked_question", False)) or (
        not done and "?" in assistant_message
    )
    next_round = clarification_round + 1 if asked_question else clarification_round

    result: dict[str, Any] = {
        "raw_messages": [
            *raw_messages,
            {"role": "assistant", "content": assistant_message},
        ],
        "clarification_round": next_round,
        "clarification_prompt": {} if done else _extract_clarification_prompt(payload),
    }
    if done:
        result["constraints"] = _normalize_constraints(payload.get("constraints", {}))

    return result
