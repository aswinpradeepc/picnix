from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from graph.state import TripState
from tools.vertex import get_chat_model


SYSTEM_PROMPT = """You are a friendly Kerala local trip planner. Write a warm, conversational trip itinerary 
based ONLY on the structured data provided. Do not invent any place names, travel times, 
distances, or facts not present in the input data. Use Malayalam words occasionally for 
warmth (e.g., "njan paranjaal" / "as I'd say", "kidu trip aakum!" / "it'll be a great trip!"). 
Format: a flowing paragraph per section (morning, journey, destination, return), not bullet points.
After writing the prose, list every factual claim with its source field from the input data and 
whether it is verified (true/false). Return the result as the structured JSON schema given.
"""

COMPOSER_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prose": {
            "type": "string",
            "description": "Full human-readable itinerary text.",
        },
        "claim_audit": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "source_field": {"type": "string"},
                    "verified": {"type": "boolean"},
                },
                "required": ["claim", "source_field", "verified"],
            },
        },
    },
    "required": ["prose", "claim_audit"],
}


class ItineraryCompositionError(RuntimeError):
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


def _sectioned_prose(value: dict[str, Any]) -> str:
    ordered_keys = ["morning", "journey", "destination", "food", "return", "notes"]
    segments: list[str] = []
    seen: set[str] = set()

    for key in ordered_keys:
        section = value.get(key)
        if isinstance(section, str) and section.strip():
            segments.append(section.strip())
            seen.add(key)

    for key, section in value.items():
        if key in seen:
            continue
        if isinstance(section, str) and section.strip():
            segments.append(section.strip())

    return "\n\n".join(segments).strip()


def _prose_value_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _sectioned_prose(value)
    if isinstance(value, list):
        segments = [_prose_value_to_text(item) for item in value]
        return "\n\n".join(segment for segment in segments if segment).strip()
    return ""


def _extract_prose(payload: dict[str, Any]) -> str:
    for key in (
        "prose",
        "itinerary",
        "itinerary_text",
        "itinerary_draft",
        "final_itinerary",
        "text",
        "content",
    ):
        prose = _prose_value_to_text(payload.get(key))
        if prose:
            return prose

    sections = _prose_value_to_text(payload.get("sections"))
    if sections:
        return sections

    raise ItineraryCompositionError("N6 response missing prose.")


def _parse_composer_payload(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        payload = content
    else:
        try:
            payload = json.loads(_extract_json_text(_content_to_text(content)))
        except json.JSONDecodeError as exc:
            raise ItineraryCompositionError("N6 returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise ItineraryCompositionError("N6 JSON response must be an object.")
    prose = _extract_prose(payload)

    claim_audit = payload.get("claim_audit", [])
    if not isinstance(claim_audit, list):
        raise ItineraryCompositionError("N6 claim_audit must be a list.")

    return {
        "prose": prose,
        "claim_audit": claim_audit,
    }


def _composer_input(state: TripState) -> dict[str, Any]:
    return {
        "constraints": state.get("constraints", {}),
        "timeline": state.get("timeline", []),
        "route": state.get("route", {}),
        "validated_destination": state.get("validated_destination", {}),
        "food_stops": state.get("food_stops", []),
        "food_availability": state.get("food_availability", []),
        "claim_failures": state.get("claim_failures", []),
    }


def _unverified_claims(claim_audit: list[Any]) -> list[str]:
    claims: list[str] = []
    for entry in claim_audit:
        if not isinstance(entry, dict):
            continue
        if bool(entry.get("verified", False)):
            continue
        claim = str(entry.get("claim", "")).strip()
        if claim:
            claims.append(claim)
    return claims


def _split_sentence_like_segments(prose: str) -> list[str]:
    segments: list[str] = []
    start = 0
    for match in re.finditer(r"([.!?])(\s+|$)", prose):
        end = match.end()
        segment = prose[start:end].strip()
        if segment:
            segments.append(segment)
        start = end

    tail = prose[start:].strip()
    if tail:
        segments.append(tail)
    if not segments and prose.strip():
        segments.append(prose.strip())
    return segments


def _remove_unverified_claims(prose: str, claim_audit: list[Any]) -> str:
    claims = _unverified_claims(claim_audit)
    if not claims:
        return prose.strip()

    filtered_segments: list[str] = []
    for segment in _split_sentence_like_segments(prose):
        normalized_segment = segment.lower()
        if any(claim.lower() in normalized_segment for claim in claims):
            continue
        filtered_segments.append(segment)

    return " ".join(filtered_segments).strip()


def compose_itinerary(
    state: TripState,
    *,
    model: Any | None = None,
) -> dict[str, Any]:
    """Read N5-validated structured trip data and write `itinerary_draft` prose with unverified claims removed."""
    chat_model = model or get_chat_model(
        temperature=0.3,
        response_mime_type="application/json",
        response_schema=COMPOSER_RESPONSE_SCHEMA,
    )
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(_composer_input(state), sort_keys=True)),
    ]
    response = chat_model.invoke(messages)
    payload = _parse_composer_payload(response.content)
    itinerary_draft = _remove_unverified_claims(
        payload["prose"],
        payload["claim_audit"],
    )
    return {"itinerary_draft": itinerary_draft}
