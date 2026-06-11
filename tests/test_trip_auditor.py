import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def auditor():
    spec = importlib.util.spec_from_file_location(
        "trip_auditor_page", Path("pages/1_Trip_Auditor.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phoenix_mcp_connection_omits_api_key_when_blank(auditor) -> None:
    connection = auditor.phoenix_mcp_connection(base_url="http://phoenix:6006", api_key="")

    phoenix = connection["phoenix"]
    assert phoenix["command"] == "npx"
    assert phoenix["transport"] == "stdio"
    assert "--baseUrl" in phoenix["args"]
    assert "http://phoenix:6006" in phoenix["args"]
    assert "--apiKey" not in phoenix["args"]


def test_phoenix_mcp_connection_passes_api_key_when_set(auditor) -> None:
    connection = auditor.phoenix_mcp_connection(
        base_url="http://phoenix:6006", api_key="secret-key"
    )

    args = connection["phoenix"]["args"]
    assert args[args.index("--apiKey") + 1] == "secret-key"


def test_condense_span_clips_long_attributes(auditor) -> None:
    record = {
        "name": "n3_validator",
        "span_kind": "CHAIN",
        "start_time": "2026-06-12T08:00:00Z",
        "end_time": "2026-06-12T08:00:02Z",
        "status_code": "OK",
        "status_message": None,
        "attributes": {"input.value": "x" * 5000, "session.id": "thread-1"},
    }

    condensed = auditor.condense_span(record)

    assert condensed["name"] == "n3_validator"
    assert condensed["status_message"] == ""
    assert condensed["attributes"]["session.id"] == "thread-1"
    assert len(condensed["attributes"]["input.value"]) < 5000
    assert condensed["attributes"]["input.value"].endswith("…[truncated]")


def test_fetch_session_spans_filters_by_session_id(auditor, monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"name": "n4_route", "attributes": {}}], "next_cursor": None}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update(url=url, params=params, headers=headers, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr(auditor.requests, "get", fake_get)
    monkeypatch.setattr(
        auditor, "SETTINGS", replace(auditor.SETTINGS, phoenix_api_key="phoenix-key")
    )

    spans = auditor.fetch_session_spans("thread-abc")

    assert captured["url"].endswith(f"/v1/projects/{auditor.SETTINGS.arize_project_name}/spans")
    assert captured["params"]["attribute"] == "session.id:thread-abc"
    assert captured["headers"]["Authorization"] == "Bearer phoenix-key"
    assert spans == [
        {
            "name": "n4_route",
            "span_kind": None,
            "start_time": None,
            "end_time": None,
            "status_code": None,
            "status_message": "",
            "attributes": {},
        }
    ]


@pytest.fixture
def scoped_tools(auditor, monkeypatch):
    def fake_threads(pool, username, *, limit):
        assert username == "alice"
        return [
            {"thread_id": "thread-owned", "title": "Beach day", "status": "completed"},
        ]

    def fake_spans(thread_id, limit=auditor.SPAN_FETCH_LIMIT):
        return [{"name": "n4_route", "attributes": {"session.id": thread_id}}]

    monkeypatch.setattr(auditor, "list_user_trip_threads", fake_threads)
    monkeypatch.setattr(auditor, "fetch_session_spans", fake_spans)

    tools = auditor.build_scoped_tools(object(), "alice", current_thread_id="thread-live")
    return {tool.name: tool for tool in tools}


def test_scoped_tools_list_my_trips_includes_current_session(scoped_tools) -> None:
    listing = json.loads(scoped_tools["list_my_trips"].invoke({}))

    thread_ids = [row["thread_id"] for row in listing]
    assert thread_ids == ["thread-live", "thread-owned"]


def test_scoped_tools_deny_foreign_thread_ids(scoped_tools) -> None:
    result = scoped_tools["get_trip_spans"].invoke({"thread_id": "someone-elses-thread"})

    assert result.startswith("Access denied")


def test_scoped_tools_fetch_owned_and_current_threads(scoped_tools) -> None:
    owned = json.loads(scoped_tools["get_trip_spans"].invoke({"thread_id": "thread-owned"}))
    live = json.loads(scoped_tools["get_trip_spans"].invoke({"thread_id": "thread-live"}))

    assert owned[0]["attributes"]["session.id"] == "thread-owned"
    assert live[0]["attributes"]["session.id"] == "thread-live"
