import json

from langchain_core.messages import HumanMessage, SystemMessage

from graph.nodes.n6_composer import COMPOSER_RESPONSE_SCHEMA, compose_itinerary


class FakeResponse:
    def __init__(self, content) -> None:
        self.content = content


class FakeModel:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.invocations = []

    def invoke(self, messages):
        self.invocations.append(messages)
        if isinstance(self.payload, str):
            return FakeResponse(self.payload)
        return FakeResponse(json.dumps(self.payload))


def base_state() -> dict:
    return {
        "constraints": {
            "start_location": "Kochi",
            "departure_time": "07:00",
            "duration_hours": 6,
            "vehicle": "car",
            "interests": ["nature"],
        },
        "validated_destination": {
            "place_id": "dest-1",
            "name": "Athirappilly Falls",
            "coords": {"lat": 10.2859, "lng": 76.5696},
            "types": ["tourist_attraction"],
        },
        "route": {
            "total_distance_meters": 82000,
            "planned_duration_seconds": 14400,
            "legs": [
                {
                    "type": "outbound",
                    "from": "Kochi",
                    "to": "Athirappilly Falls",
                    "duration_seconds": 3600,
                    "depart_time": "07:00",
                    "arrive_time": "08:00",
                }
            ],
        },
        "food_stops": [],
        "food_availability": [
            {
                "meal": "dinner",
                "status": "eat_at_home",
                "time": "11:00",
                "notes": "Dinner can be at home.",
            }
        ],
        "timeline": [
            {
                "time": "07:00",
                "label": "Depart Kochi",
                "coords": {"lat": 9.9312, "lng": 76.2673},
                "type": "start",
                "notes": "Start the trip.",
            },
            {
                "time": "08:00",
                "label": "Athirappilly Falls",
                "coords": {"lat": 10.2859, "lng": 76.5696},
                "type": "destination",
                "notes": "Spend 2 hr here.",
            },
            {
                "time": "10:00",
                "label": "Leave Athirappilly Falls",
                "coords": {"lat": 10.2859, "lng": 76.5696},
                "type": "return_departure",
                "notes": "Start the return journey.",
            },
            {
                "time": "11:00",
                "label": "Back at Kochi",
                "coords": {"lat": 9.9312, "lng": 76.2673},
                "type": "return",
                "notes": "Trip ends.",
            },
        ],
        "claim_failures": [
            {
                "field": "timeline",
                "issue": "Destination dwell time is short but usable.",
                "severity": "warning",
            }
        ],
    }


def test_composer_writes_itinerary_draft_from_verified_model_output() -> None:
    model = FakeModel(
        {
            "prose": "Morning: Leave Kochi at 07:00. Reach Athirappilly Falls at 08:00. Return by 11:00.",
            "claim_audit": [
                {
                    "claim": "Leave Kochi at 07:00",
                    "source_field": "timeline[0]",
                    "verified": True,
                },
                {
                    "claim": "Reach Athirappilly Falls at 08:00",
                    "source_field": "timeline[1]",
                    "verified": True,
                },
            ],
        }
    )

    result = compose_itinerary(base_state(), model=model)

    assert result == {
        "itinerary_draft": (
            "Morning: Leave Kochi at 07:00. Reach Athirappilly Falls at 08:00. Return by 11:00."
        )
    }
    assert isinstance(model.invocations[0][0], SystemMessage)
    assert isinstance(model.invocations[0][1], HumanMessage)
    assert "Athirappilly Falls" in model.invocations[0][1].content
    assert "Destination dwell time is short but usable." in model.invocations[0][1].content


def test_composer_strips_sentence_with_unverified_claim() -> None:
    model = FakeModel(
        {
            "prose": (
                "Morning: Leave Kochi at 07:00. "
                "Athirappilly Falls has boating. "
                "Return by 11:00."
            ),
            "claim_audit": [
                {
                    "claim": "Leave Kochi at 07:00",
                    "source_field": "timeline[0]",
                    "verified": True,
                },
                {
                    "claim": "Athirappilly Falls has boating",
                    "source_field": "",
                    "verified": False,
                },
                {
                    "claim": "Return by 11:00",
                    "source_field": "timeline[3]",
                    "verified": True,
                },
            ],
        }
    )

    result = compose_itinerary(base_state(), model=model)

    assert result["itinerary_draft"] == "Morning: Leave Kochi at 07:00. Return by 11:00."
    assert "boating" not in result["itinerary_draft"]


def test_composer_extracts_fenced_json_response() -> None:
    model = FakeModel(
        """```json
        {
          "prose": "Journey: Start at 07:00 and come back at 11:00.",
          "claim_audit": [
            {"claim": "Start at 07:00", "source_field": "timeline[0]", "verified": true}
          ]
        }
        ```"""
    )

    result = compose_itinerary(base_state(), model=model)

    assert result["itinerary_draft"] == "Journey: Start at 07:00 and come back at 11:00."


def test_composer_extracts_json_when_model_adds_prose() -> None:
    model = FakeModel(
        """
        Here is the itinerary JSON:
        {
          "prose": "Destination: Spend 2 hr at Athirappilly Falls.",
          "claim_audit": []
        }
        """
    )

    result = compose_itinerary(base_state(), model=model)

    assert result["itinerary_draft"] == "Destination: Spend 2 hr at Athirappilly Falls."


def test_composer_accepts_itinerary_alias_from_unconstrained_json_output() -> None:
    model = FakeModel(
        {
            "itinerary": "Morning: Leave Kochi at 07:00. Return by 11:00.",
            "claim_audit": [],
        }
    )

    result = compose_itinerary(base_state(), model=model)

    assert result["itinerary_draft"] == "Morning: Leave Kochi at 07:00. Return by 11:00."


def test_composer_flattens_sectioned_itinerary_alias() -> None:
    model = FakeModel(
        {
            "itinerary": {
                "morning": "Morning: Leave Kochi at 07:00.",
                "journey": "Journey: Reach Athirappilly Falls at 08:00.",
                "return": "Return: Back at Kochi by 11:00.",
            },
            "claim_audit": [],
        }
    )

    result = compose_itinerary(base_state(), model=model)

    assert result["itinerary_draft"] == (
        "Morning: Leave Kochi at 07:00.\n\n"
        "Journey: Reach Athirappilly Falls at 08:00.\n\n"
        "Return: Back at Kochi by 11:00."
    )


def test_composer_configures_default_model_for_json_mode(monkeypatch) -> None:
    from graph.nodes import n6_composer

    captured_kwargs = {}

    def fake_get_chat_model(**kwargs):
        captured_kwargs.update(kwargs)
        return FakeModel(
            {
                "prose": "Return: Back at Kochi by 11:00.",
                "claim_audit": [
                    {
                        "claim": "Back at Kochi by 11:00",
                        "source_field": "timeline[3]",
                        "verified": True,
                    }
                ],
            }
        )

    monkeypatch.setattr(n6_composer, "get_chat_model", fake_get_chat_model)

    result = n6_composer.compose_itinerary(base_state())

    assert result["itinerary_draft"] == "Return: Back at Kochi by 11:00."
    assert captured_kwargs["temperature"] == 0.3
    assert captured_kwargs["response_mime_type"] == "application/json"
    assert captured_kwargs["response_schema"] == COMPOSER_RESPONSE_SCHEMA
    assert captured_kwargs["response_schema"]["required"] == ["prose", "claim_audit"]
