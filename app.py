from __future__ import annotations

import streamlit as st

from graph.graph import (
    initial_trip_state,
    request_next_candidate,
    run_candidate_discovery,
    run_intent_turn,
    run_route_builder,
)


def format_km(distance_meters: int | float | None) -> str:
    return f"{(distance_meters or 0) / 1000:.1f} km"


def format_duration(seconds: int | float | None) -> str:
    total_minutes = round((seconds or 0) / 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours and not minutes:
        return f"{hours} hr"
    if hours:
        return f"{hours} hr {minutes} min"
    return f"{minutes} min"


def destination_summary(destination: dict) -> dict:
    return {
        "name": destination.get("name", "Destination"),
        "distance": format_km(destination.get("distance_meters")),
        "duration": format_duration(destination.get("travel_time_seconds")),
        "description": destination.get("description") or "Validated destination candidate.",
        "notes": destination.get("notes", []),
    }


def destination_empty_message(state: dict) -> str:
    if state.get("constraints"):
        return "No more open and reachable suggestions found for this trip window."
    return "Once Picnix validates a destination, it will appear here."


def timeline_rows(timeline: list[dict]) -> list[dict]:
    return [
        {
            "Time": entry.get("time", ""),
            "Stop": entry.get("label", ""),
            "Type": entry.get("type", ""),
            "Notes": entry.get("notes", ""),
        }
        for entry in timeline
    ]


def food_availability_rows(food_availability: list[dict]) -> list[dict]:
    return [
        {
            "Meal": entry.get("meal", ""),
            "Decision": entry.get("status", "").replace("_", " "),
            "Time": entry.get("time", ""),
            "Notes": entry.get("notes", ""),
        }
        for entry in food_availability
    ]


def show_destination_actions(state: dict) -> bool:
    return not bool(state.get("user_confirmed"))


def ensure_session_state() -> None:
    if "graph_state" not in st.session_state:
        st.session_state.graph_state = initial_trip_state()
        st.session_state.graph_state = run_intent_turn(st.session_state.graph_state)
    if "partial_demo_notice" not in st.session_state:
        st.session_state.partial_demo_notice = ""


def render_chat() -> None:
    for message in st.session_state.graph_state["raw_messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])


def handle_user_message(user_message: str) -> None:
    with st.spinner("Thinking through the trip constraints..."):
        st.session_state.graph_state = run_intent_turn(
            st.session_state.graph_state,
            user_message,
        )

    if st.session_state.graph_state.get("constraints") and not st.session_state.graph_state.get("candidates"):
        with st.spinner("Finding and validating destination candidates..."):
            st.session_state.graph_state = run_candidate_discovery(st.session_state.graph_state)


def render_destination_panel() -> None:
    destination = st.session_state.graph_state.get("validated_destination", {})
    if not destination:
        st.info(destination_empty_message(st.session_state.graph_state))
        return

    summary = destination_summary(destination)
    st.subheader(summary["name"])
    cols = st.columns(2)
    cols[0].metric("Distance", summary["distance"])
    cols[1].metric("Travel time", summary["duration"])
    st.write(summary["description"])
    for note in summary["notes"]:
        st.info(note)

    validated_candidates = st.session_state.graph_state.get("validated_candidates", [])
    presented_index = int(st.session_state.graph_state.get("presented_candidate_index", 0))
    has_next_candidate = presented_index + 1 < len(validated_candidates)

    if show_destination_actions(st.session_state.graph_state):
        yes_col, another_col = st.columns(2)
        if yes_col.button("Yes, plan this!", use_container_width=True):
            accepted_state = {
                **st.session_state.graph_state,
                "user_confirmed": True,
            }
            with st.spinner("Building the round-trip route and checking food stops..."):
                st.session_state.graph_state = run_route_builder(accepted_state)
            st.session_state.partial_demo_notice = (
                "Route built. N5 itinerary composer is the next implementation step."
            )
            st.rerun()
        if another_col.button(
            "Show me another",
            disabled=not has_next_candidate,
            use_container_width=True,
        ):
            with st.spinner("Checking the next validated option..."):
                st.session_state.graph_state = request_next_candidate(st.session_state.graph_state)
            st.rerun()
        if not has_next_candidate:
            st.caption("No more validated suggestions are queued for this trip window.")
    else:
        st.caption(
            "Destination confirmed. The validated suggestion controls are hidden for this trip."
        )

    if st.session_state.partial_demo_notice:
        st.success(st.session_state.partial_demo_notice)

    route = st.session_state.graph_state.get("route", {})
    if route:
        st.divider()
        st.subheader("Route")
        route_cols = st.columns(2)
        route_cols[0].metric(
            "Round trip",
            format_km(route.get("total_distance_meters")),
        )
        route_cols[1].metric(
            "Planned duration",
            format_duration(route.get("planned_duration_seconds")),
        )
        rows = timeline_rows(st.session_state.graph_state.get("timeline", []))
        if rows:
            st.table(rows)
        food_rows = food_availability_rows(
            st.session_state.graph_state.get("food_availability", [])
        )
        if food_rows:
            st.subheader("Food")
            st.table(food_rows)


def main() -> None:
    st.set_page_config(page_title="Picnix", layout="wide")
    ensure_session_state()

    left, right = st.columns([0.4, 0.6])
    with left:
        st.title("Picnix")
        render_chat()
        if user_message := st.chat_input("Tell me your trip mood, starting point, time, and vehicle"):
            handle_user_message(user_message)
            st.rerun()

    with right:
        st.title("Trip Preview")
        st.caption("Partial demo: N1 intent collection through N4 route building.")
        render_destination_panel()
        st.divider()
        st.info("Map route rendering arrives after N7 GeoJSON formatter.")


if __name__ == "__main__":
    main()
