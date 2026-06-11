"""Picnix Trace Auditor — standalone meta-agent page.

Answers questions about Phoenix traces with a Gemini agent. Two access modes:

- **Admin** (username in ``ADMIN_USERNAMES``): full Arize Phoenix MCP toolset
  (``npx @arizeai/phoenix-mcp``) with org-wide trace access.
- **User** (any other logged-in account): a locked-down pair of Python tools.
  Trip ownership is enforced server-side against the ``trip_runs`` table and
  spans are fetched from Phoenix's REST API filtered by ``session.id`` (the
  LangGraph thread id), so the model has no tool that can reach another
  user's traces. Prompt instructions are NOT the privacy boundary — the tool
  surface is.

This page is deliberately independent of the trip planner: it never imports
``graph/`` and never touches a LangGraph thread. It reuses
``config/settings.py`` for configuration, ``tools/vertex.py::get_chat_model()``
for the retrying Gemini client, and ``persistence/database.py`` for ownership
lookups.
"""

import asyncio
import json
import shutil
from typing import Any

import requests
import streamlit as st
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool, tool
from langchain_mcp_adapters.client import MultiServerMCPClient

from config.settings import SETTINGS
from persistence.database import (
    create_connection_pool,
    list_user_trip_threads,
    normalize_username,
)
from tools.vertex import REASONING_GEMINI_MODEL, get_chat_model

PAGE_TITLE = "Picnix Trace Auditor"
PHOENIX_MCP_PACKAGE = "@arizeai/phoenix-mcp@latest"
MAX_TOOL_ROUNDS = 8
MAX_HISTORY_MESSAGES = 12
TOOL_RESULT_PREVIEW_CHARS = 600
SPAN_FETCH_LIMIT = 100
SPAN_ATTRIBUTE_CLIP_CHARS = 400
PHOENIX_REQUEST_TIMEOUT_SECONDS = 30
OWNERSHIP_LOOKUP_LIMIT = 500

ADMIN_SYSTEM_PROMPT = (
    "You are the Picnix Trace Auditor, an observability analyst for a trip "
    "planner app whose LangGraph nodes (n1_intent, n2_isochrone, n3_validator, "
    "n4_route, n5_validator, n6_composer, n7_formatter, n8_editor) emit "
    f"OpenInference traces to a Phoenix project named "
    f"'{SETTINGS.arize_project_name}'. Use the Phoenix MCP tools to list "
    "projects, fetch traces and spans, and inspect span attributes before "
    "answering. Ground every claim in the trace data you actually retrieved; "
    "if the data is missing or a tool fails, say so plainly instead of "
    "guessing. Summarize findings with concrete numbers (counts, latencies, "
    "error messages) and name the node or span the evidence came from."
)

SCOPED_SYSTEM_PROMPT = (
    "You are the Picnix Trace Auditor, helping a trip planner user understand "
    "the observability traces of their own trips. The app's LangGraph nodes "
    "(n1_intent, n2_isochrone, n3_validator, n4_route, n5_validator, "
    "n6_composer, n7_formatter, n8_editor) emit OpenInference spans grouped "
    "by trip thread id. Start with list_my_trips to find the user's trips, "
    "then get_trip_spans for the relevant thread ids. You only have access to "
    "this user's trips. Ground every claim in span data you actually "
    "retrieved; if data is missing or a tool fails, say so plainly instead of "
    "guessing. Summarize with concrete numbers and name the node or span the "
    "evidence came from."
)


@st.cache_resource
def get_auditor_database_pool() -> Any:
    """Connection pool for ownership lookups, cached for the Streamlit server."""
    return create_connection_pool()


def is_admin_user() -> bool:
    """True when the logged-in session username is in the ADMIN_USERNAMES allowlist.

    Admins get the full Phoenix MCP toolset, which can read trace data from
    every account. An empty allowlist simply means no one gets admin mode.
    """
    username = session_username()
    return bool(username) and username in SETTINGS.admin_usernames


def session_username() -> str:
    """Normalized username of the logged-in streamlit-authenticator session."""
    return normalize_username(str(st.session_state.get("username") or ""))


def phoenix_mcp_connection(
    base_url: str = SETTINGS.phoenix_base_url,
    api_key: str = SETTINGS.phoenix_api_key,
) -> dict[str, dict[str, Any]]:
    """Build the MultiServerMCPClient connection map for the Phoenix MCP server.

    Reads the Phoenix base URL and optional API key from settings and returns a
    single stdio connection that launches the Node-based server via npx.
    """
    args = ["-y", PHOENIX_MCP_PACKAGE, "--baseUrl", base_url]
    if api_key:
        args += ["--apiKey", api_key]
    return {"phoenix": {"command": "npx", "args": args, "transport": "stdio"}}


def clip_value(value: Any, max_chars: int = SPAN_ATTRIBUTE_CLIP_CHARS) -> str:
    """Render an attribute value as text, truncated so spans stay readable."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) > max_chars:
        return text[:max_chars] + "…[truncated]"
    return text


def condense_span(record: dict[str, Any]) -> dict[str, Any]:
    """Reduce one Phoenix REST span record to the fields useful for auditing."""
    attributes = record.get("attributes") or {}
    if not isinstance(attributes, dict):
        attributes = {"raw": attributes}
    return {
        "name": record.get("name"),
        "span_kind": record.get("span_kind"),
        "start_time": record.get("start_time"),
        "end_time": record.get("end_time"),
        "status_code": record.get("status_code"),
        "status_message": record.get("status_message") or "",
        "attributes": {key: clip_value(value) for key, value in attributes.items()},
    }


def fetch_session_spans(thread_id: str, limit: int = SPAN_FETCH_LIMIT) -> list[dict[str, Any]]:
    """Fetch spans for one trip thread from Phoenix's REST API.

    Filters server-side on the ``session.id`` span attribute, which the
    OpenInference LangChain instrumentation sets to the LangGraph thread id.
    """
    headers = {}
    if SETTINGS.phoenix_api_key:
        headers["Authorization"] = f"Bearer {SETTINGS.phoenix_api_key}"
    response = requests.get(
        f"{SETTINGS.phoenix_base_url}/v1/projects/{SETTINGS.arize_project_name}/spans",
        params={"attribute": f"session.id:{thread_id}", "limit": limit},
        headers=headers,
        timeout=PHOENIX_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    records = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        return [{"raw": clip_value(payload, 2000)}]
    return [condense_span(record) for record in records if isinstance(record, dict)]


def build_scoped_tools(pool: Any, username: str, current_thread_id: str = "") -> list[BaseTool]:
    """Build the per-user tool pair with server-side ownership enforcement.

    Both tools close over the connection pool and the already-authenticated
    username; the model never supplies an identity. ``get_trip_spans``
    re-checks ownership against trip_runs on every call (plus the session's
    in-flight thread, which may not be persisted yet) and refuses anything
    else, so prompt injection cannot widen the scope.
    """

    def owned_threads() -> list[dict[str, Any]]:
        return list_user_trip_threads(pool, username, limit=OWNERSHIP_LOOKUP_LIMIT)

    @tool
    def list_my_trips() -> str:
        """List the current user's trip plans: thread_id, title, status, and dates.

        Call this first to discover which thread ids can be passed to
        get_trip_spans.
        """
        rows = owned_threads()
        if current_thread_id and current_thread_id not in {row["thread_id"] for row in rows}:
            rows.insert(
                0,
                {"thread_id": current_thread_id, "title": "Current session", "status": "running"},
            )
        if not rows:
            return "No trips found for this account yet. Plan a trip first."
        return json.dumps(rows, default=str)

    @tool
    def get_trip_spans(thread_id: str) -> str:
        """Fetch the Phoenix trace spans for one of the current user's trips.

        thread_id must be one of the ids returned by list_my_trips. Returns
        condensed span records (name, kind, times, status, clipped attributes).
        """
        allowed = {row["thread_id"] for row in owned_threads()}
        if current_thread_id:
            allowed.add(current_thread_id)
        if thread_id not in allowed:
            return (
                "Access denied: that thread id does not belong to the current "
                "user. Use list_my_trips to see the available thread ids."
            )
        spans = fetch_session_spans(thread_id)
        if not spans:
            return f"No spans found in Phoenix for thread {thread_id}."
        return json.dumps(spans, default=str)

    return [list_my_trips, get_trip_spans]


def message_text(message: BaseMessage) -> str:
    """Flatten a model message's content (string or content-part list) to text."""
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
        return "\n".join(part for part in parts if part)
    return str(content)


def history_messages(history: list[dict[str, str]]) -> list[BaseMessage]:
    """Convert stored chat history dicts into LangChain messages for the model."""
    recent = history[-MAX_HISTORY_MESSAGES:]
    return [
        HumanMessage(content=entry["content"])
        if entry["role"] == "user"
        else AIMessage(content=entry["content"])
        for entry in recent
    ]


async def load_admin_tools() -> list[BaseTool]:
    """Load the full Phoenix MCP toolset (admin mode only)."""
    client = MultiServerMCPClient(phoenix_mcp_connection())
    return await client.get_tools()


async def answer_question(
    question: str,
    history: list[dict[str, str]],
    tools: list[BaseTool],
    system_prompt: str,
) -> tuple[str, list[dict[str, str]]]:
    """Run one auditor turn: loop the model over the given tools until it answers.

    Reads the chat history and the user's question; returns the final answer
    text plus a log of every tool invocation for display. The trip planner
    graph is never involved.
    """
    tools_by_name = {tool_item.name: tool_item for tool_item in tools}
    model = get_chat_model(model=REASONING_GEMINI_MODEL, temperature=1.0).bind_tools(tools)

    messages: list[BaseMessage] = [
        SystemMessage(content=system_prompt),
        *history_messages(history),
        HumanMessage(content=question),
    ]
    tool_log: list[dict[str, str]] = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = await asyncio.to_thread(model.invoke, messages)
        messages.append(response)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            return message_text(response), tool_log

        for call in tool_calls:
            tool_item = tools_by_name.get(call["name"])
            if tool_item is None:
                result = f"Unknown tool: {call['name']}"
            else:
                try:
                    result = await tool_item.ainvoke(call["args"])
                except Exception as exc:  # surface tool failures to the model
                    result = f"Tool {call['name']} failed: {exc}"
            result_text = result if isinstance(result, str) else json.dumps(result, default=str)
            tool_log.append(
                {
                    "tool": call["name"],
                    "args": json.dumps(call.get("args", {}), default=str),
                    "result": result_text[:TOOL_RESULT_PREVIEW_CHARS],
                }
            )
            messages.append(ToolMessage(content=result_text, tool_call_id=call["id"]))

    return (
        "I hit the tool-call limit for a single question without reaching a "
        "final answer. Try a narrower question.",
        tool_log,
    )


async def run_turn(
    question: str, history: list[dict[str, str]], admin: bool
) -> tuple[str, list[dict[str, str]]]:
    """Assemble the mode-appropriate toolset and answer one question."""
    if admin:
        tools = await load_admin_tools()
        system_prompt = ADMIN_SYSTEM_PROMPT
    else:
        tools = build_scoped_tools(
            get_auditor_database_pool(),
            session_username(),
            str(st.session_state.get("thread_id") or ""),
        )
        system_prompt = SCOPED_SYSTEM_PROMPT
    return await answer_question(question, history, tools, system_prompt)


def render_tool_log(tool_log: list[dict[str, str]]) -> None:
    """Render the tool invocations of one turn inside an expander."""
    if not tool_log:
        return
    with st.expander(f"Trace tool calls ({len(tool_log)})"):
        for entry in tool_log:
            st.markdown(f"**{entry['tool']}**  `{entry['args']}`")
            st.code(entry["result"], language="json")


def render_page() -> None:
    """Render the auditor chat page: auth guard, mode selection, chat loop."""
    st.set_page_config(page_title=PAGE_TITLE, page_icon="🔍", layout="wide")
    st.title(f"🔍 {PAGE_TITLE}")

    if not st.session_state.get("authentication_status"):
        st.info("Log in on the main Picnix page to use the trace auditor.")
        st.stop()

    admin = is_admin_user()
    if admin:
        st.caption(
            "Admin mode — full Phoenix MCP access across all accounts. Try "
            "\"Summarize the N3 validation failures from the last 10 trips.\""
        )
        if shutil.which("npx") is None:
            st.error(
                "Node.js (`npx`) was not found on this host. Admin mode "
                f"launches the Phoenix MCP server with `npx {PHOENIX_MCP_PACKAGE}`. "
                "Install Node.js, or rebuild the Docker image (the Dockerfile "
                "installs it)."
            )
            st.stop()
    else:
        st.caption(
            "Ask questions about your own trips' traces — e.g. "
            "\"Why did my last plan drop a destination?\""
        )

    with st.sidebar:
        st.subheader("Auditor configuration")
        scope_line = (
            "- **Scope:** all accounts (admin, Phoenix MCP)\n"
            if admin
            else f"- **Scope:** trips of `{session_username()}` only\n"
        )
        st.markdown(
            scope_line
            + f"- **Phoenix:** `{SETTINGS.phoenix_base_url}`\n"
            f"- **Project:** `{SETTINGS.arize_project_name}`\n"
            f"- **Model:** `{REASONING_GEMINI_MODEL}`"
        )
        if st.button("Clear auditor chat"):
            st.session_state.auditor_messages = []
            st.rerun()

    if "auditor_messages" not in st.session_state:
        st.session_state.auditor_messages = []

    for entry in st.session_state.auditor_messages:
        with st.chat_message(entry["role"]):
            st.markdown(entry["content"])
            render_tool_log(entry.get("tool_log", []))

    question = st.chat_input("Ask about the Phoenix traces…")
    if not question:
        return

    with st.chat_message("user"):
        st.markdown(question)

    history = [
        {"role": entry["role"], "content": entry["content"]}
        for entry in st.session_state.auditor_messages
    ]
    st.session_state.auditor_messages.append({"role": "user", "content": question})

    with st.chat_message("assistant"):
        with st.spinner("Querying Phoenix traces…"):
            try:
                answer, tool_log = asyncio.run(run_turn(question, history, admin))
            except Exception as exc:
                answer, tool_log = (
                    "I couldn't complete the trace lookup against "
                    f"`{SETTINGS.phoenix_base_url}`: {exc}",
                    [],
                )
        st.markdown(answer)
        render_tool_log(tool_log)

    st.session_state.auditor_messages.append(
        {"role": "assistant", "content": answer, "tool_log": tool_log}
    )


if __name__ == "__main__":
    render_page()
