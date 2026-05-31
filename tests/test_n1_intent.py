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
    assert result["constraints"]["duration_hours"] == 6.0
