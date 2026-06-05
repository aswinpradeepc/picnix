import json

from langchain_core.messages import HumanMessage, SystemMessage


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeModel:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.invocations = []

    def invoke(self, messages):
        self.invocations.append(messages)
        return FakeResponse(json.dumps(self.payload))


def test_intent_node_returns_opening_message_without_model_call() -> None:
    from graph.nodes.n1_intent import OPENING_MESSAGE, collect_intent

    model = FakeModel({})

    result = collect_intent({"raw_messages": [], "clarification_round": 0}, model=model)

    assert result == {
        "raw_messages": [{"role": "assistant", "content": OPENING_MESSAGE}],
        "clarification_round": 0,
    }
    assert model.invocations == []


def test_intent_node_extracts_constraints_from_model_json() -> None:
    from graph.nodes.n1_intent import collect_intent

    model = FakeModel(
        {
            "assistant_message": "Kidu, I have enough to plan this.",
            "done": True,
            "asked_question": False,
            "constraints": {
                "start_location": "Kochi",
                "departure_time": "09:30",
                "duration_hours": "8",
                "group_size": "2",
                "vehicle": "car",
                "interests": ["food", "culture"],
                "budget_feel": "medium",
            },
        }
    )

    result = collect_intent(
        {
            "raw_messages": [
                {
                    "role": "user",
                    "content": "We are 2 people starting from Kochi, have 8 hours, car, food and culture.",
                }
            ],
            "clarification_round": 0,
        },
        model=model,
    )

    assert result["constraints"] == {
        "start_location": "Kochi",
        "departure_time": "09:30",
        "duration_hours": 8.0,
        "group_size": 2,
        "vehicle": "car",
        "interests": ["food", "culture"],
        "budget_feel": "medium",
    }
    assert result["raw_messages"][-1] == {
        "role": "assistant",
        "content": "Kidu, I have enough to plan this.",
    }
    assert result["clarification_round"] == 0
    assert isinstance(model.invocations[0][0], SystemMessage)
    assert isinstance(model.invocations[0][1], HumanMessage)


def test_intent_node_increments_clarification_round_for_question() -> None:
    from graph.nodes.n1_intent import collect_intent

    model = FakeModel(
        {
            "assistant_message": "Nice. Where are you starting from?",
            "done": False,
            "asked_question": True,
            "constraints": {},
        }
    )

    result = collect_intent(
        {
            "raw_messages": [{"role": "user", "content": "Plan something for tomorrow"}],
            "clarification_round": 1,
        },
        model=model,
    )

    assert "constraints" not in result
    assert result["clarification_round"] == 2
    assert result["raw_messages"][-1]["content"] == "Nice. Where are you starting from?"


def test_intent_node_strips_markdown_fenced_json() -> None:
    from graph.nodes.n1_intent import collect_intent

    model = FakeModel({})
    model.invoke = lambda messages: FakeResponse(
        """```json
        {
          "assistant_message": "Set. I will assume low budget.",
          "done": true,
          "asked_question": false,
          "constraints": {
            "start_location": "Thrissur",
            "departure_time": "6am",
            "duration_hours": 6,
            "group_size": 1,
            "vehicle": "bike",
            "interests": ["nature"],
            "budget_feel": "low"
          }
        }
        ```"""
    )

    result = collect_intent(
        {
            "raw_messages": [{"role": "user", "content": "Solo from Thrissur by bike for 6 hours"}],
            "clarification_round": 3,
        },
        model=model,
    )

    assert result["constraints"]["start_location"] == "Thrissur"
    assert result["constraints"]["departure_time"] == "06:00"
    assert result["constraints"]["duration_hours"] == 6.0


def test_intent_node_extracts_json_when_model_adds_prose() -> None:
    from graph.nodes.n1_intent import collect_intent

    model = FakeModel({})
    model.invoke = lambda messages: FakeResponse(
        """
        Sure, here is the JSON:
        {
          "assistant_message": "Set. I have enough detail.",
          "done": true,
          "asked_question": false,
          "constraints": {
            "start_location": "Kollam",
            "departure_time": "evening",
            "duration_hours": 5,
            "group_size": 3,
            "vehicle": "car",
            "interests": ["beach"],
            "budget_feel": "low"
          }
        }
        """
    )

    result = collect_intent(
        {
            "raw_messages": [{"role": "user", "content": "Kollam, 5 hours, 3 people, car, beach"}],
            "clarification_round": 1,
        },
        model=model,
    )

    assert result["constraints"]["start_location"] == "Kollam"
    assert result["constraints"]["departure_time"] == "17:00"
    assert result["constraints"]["interests"] == ["beach"]


def test_intent_node_configures_model_for_json_mode(monkeypatch) -> None:
    from graph.nodes import n1_intent

    captured_kwargs = {}

    def fake_get_chat_model(**kwargs):
        captured_kwargs.update(kwargs)
        return FakeModel(
            {
                "assistant_message": "Set.",
                "done": True,
                "asked_question": False,
                "constraints": {
                    "start_location": "Kochi",
                    "departure_time": "09:00",
                    "duration_hours": 8,
                    "group_size": 2,
                    "vehicle": "car",
                    "interests": ["food"],
                    "budget_feel": "medium",
                },
            }
        )

    monkeypatch.setattr(n1_intent, "get_chat_model", fake_get_chat_model)

    n1_intent.collect_intent(
        {
            "raw_messages": [{"role": "user", "content": "Kochi, 8 hours, car, food"}],
            "clarification_round": 0,
        },
    )

    assert captured_kwargs["temperature"] == 0.1
    assert captured_kwargs["response_mime_type"] == "application/json"


def test_intent_node_reads_text_from_content_blocks() -> None:
    from graph.nodes.n1_intent import collect_intent

    model = FakeModel({})
    model.invoke = lambda messages: FakeResponse(
        [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "assistant_message": "Set.",
                        "done": True,
                        "asked_question": False,
                        "constraints": {
                            "start_location": "Alappuzha",
                            "departure_time": "",
                            "duration_hours": 4,
                            "group_size": 2,
                            "vehicle": "car",
                            "interests": ["food"],
                            "budget_feel": "medium",
                        },
                    }
                ),
            }
        ]
    )

    result = collect_intent(
        {
            "raw_messages": [{"role": "user", "content": "Alappuzha, 4 hours, car, food"}],
            "clarification_round": 0,
        },
        model=model,
    )

    assert result["constraints"]["start_location"] == "Alappuzha"
    assert result["constraints"]["departure_time"] == "17:00"


def test_intent_node_makes_reasonable_duration_guess_when_model_omits_it() -> None:
    from graph.nodes.n1_intent import collect_intent

    model = FakeModel(
        {
            "assistant_message": "Set. I will assume this is an evening food plan.",
            "done": True,
            "asked_question": False,
            "constraints": {
                "start_location": "Kochi",
                "departure_time": "evening",
                "group_size": 2,
                "vehicle": "car",
                "interests": ["food"],
                "budget_feel": "medium",
            },
        }
    )

    result = collect_intent(
        {
            "raw_messages": [{"role": "user", "content": "Kochi food plan by car"}],
            "clarification_round": 3,
        },
        model=model,
    )

    assert result["constraints"]["duration_hours"] == 4.0
