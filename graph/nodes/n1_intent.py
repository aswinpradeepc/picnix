from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from graph.state import TripState
from tools.vertex import get_chat_model


OPENING_MESSAGE = (
    "Aah, sounds like you need a good day out! Let me help plan it. "
    "Tell me - where are you starting from?"
)

SYSTEM_PROMPT = """You are N1, the Picnix intent collector.

Persona: warm, brief, enthusiastic Kerala local trip-planning friend.

Collect these constraints:
- start_location: text
- duration_hours: float
- group_size: int
- vehicle: one of bike, car, public, none
- interests: list of strings
- budget_feel: one of free, low, medium, splurge

Rules:
- Ask at most 3 question rounds total. Current clarification_round is {clarification_round}.
- Group questions naturally.
- If the user is vague and clarification_round is already 3, make reasonable assumptions and state them.
- When enough information is gathered, set done=true and return all constraints.
- Return only valid JSON with this shape:
{{
  "assistant_message": "message to show the user",
  "done": true,
  "asked_question": false,
  "constraints": {{
    "start_location": "...",
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


def _parse_payload(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(_strip_fenced_json(content))
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

    return {
        "start_location": str(raw.get("start_location", "")).strip(),
        "duration_hours": float(raw.get("duration_hours", 0)),
        "group_size": int(raw.get("group_size", 1)),
        "vehicle": vehicle,
        "interests": [str(interest).strip().lower() for interest in interests if str(interest).strip()],
        "budget_feel": budget_feel,
    }


def collect_intent(state: TripState, *, model: Any | None = None) -> dict[str, Any]:
    """Read `raw_messages` and `clarification_round`, then write updated chat history and constraints when N1 has enough information."""
    raw_messages = list(state.get("raw_messages", []))
    clarification_round = int(state.get("clarification_round", 0))

    if not raw_messages:
        return {
            "raw_messages": [{"role": "assistant", "content": OPENING_MESSAGE}],
            "clarification_round": clarification_round,
        }

    chat_model = model or get_chat_model(temperature=0.1)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT.format(clarification_round=clarification_round)),
        *[_message_from_dict(message) for message in raw_messages],
    ]
    response = chat_model.invoke(messages)
    payload = _parse_payload(str(response.content))

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
    }
    if done:
        result["constraints"] = _normalize_constraints(payload.get("constraints", {}))

    return result
