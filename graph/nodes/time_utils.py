from __future__ import annotations

from datetime import datetime, time, timedelta
import re
from typing import Any


TIME_ALIASES = {
    "early morning": "06:00",
    "morning": "09:00",
    "noon": "12:00",
    "afternoon": "14:00",
    "evening": "17:00",
    "night": "19:00",
}


def infer_departure_time(duration_hours: float, interests: list[str] | None = None) -> str:
    normalized_interests = {
        str(interest).strip().lower().replace("-", "_").replace(" ", "_")
        for interest in interests or []
    }
    if duration_hours >= 10:
        return "06:00"
    if duration_hours >= 7:
        return "08:00"
    if duration_hours <= 4 and normalized_interests.intersection({"food", "movies", "shopping"}):
        return "17:00"
    if duration_hours <= 5:
        return "15:00"
    return "10:00"


def normalize_departure_time(
    value: Any,
    *,
    duration_hours: float,
    interests: list[str] | None = None,
) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return infer_departure_time(duration_hours, interests)

    if text in TIME_ALIASES:
        return TIME_ALIASES[text]

    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*([ap]m)?", text)
    if not match:
        return infer_departure_time(duration_hours, interests)

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3)

    if meridiem:
        if hour == 12:
            hour = 0
        if meridiem == "pm":
            hour += 12

    if hour > 23 or minute > 59:
        return infer_departure_time(duration_hours, interests)
    return f"{hour:02d}:{minute:02d}"


def parse_departure_time(value: str) -> time:
    hour_text, minute_text = value.split(":", maxsplit=1)
    return time(int(hour_text), int(minute_text))


def trip_start_from_constraints(
    constraints: dict[str, Any],
    *,
    now: datetime | None = None,
) -> datetime:
    current = now or datetime.now()
    duration_hours = float(constraints.get("duration_hours", 0))
    interests = list(constraints.get("interests", []))
    departure_time = normalize_departure_time(
        constraints.get("departure_time"),
        duration_hours=duration_hours,
        interests=interests,
    )
    parsed = parse_departure_time(departure_time)
    trip_start = current.replace(
        hour=parsed.hour,
        minute=parsed.minute,
        second=0,
        microsecond=0,
    )
    if trip_start <= current:
        trip_start += timedelta(days=1)
    return trip_start
