from __future__ import annotations

import uuid
from typing import Any

import pydeck as pdk
import streamlit as st

from observability.bootstrap import configure_observability

configure_observability()

from graph.graph import (
    build_graph,
    initial_trip_state,
    load_more_candidates,
    selection_updates,
)
from tools.gmaps import generate_gmaps_link
from tools.mapbox import get_mapbox_token


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


def final_geojson_center(final_geojson: dict) -> dict:
    coordinates: list[list[float]] = []
    for feature in final_geojson.get("features", []):
        geometry = feature.get("geometry", {}) if isinstance(feature, dict) else {}
        geometry_type = geometry.get("type")
        raw_coordinates = geometry.get("coordinates")
        if geometry_type == "Point" and isinstance(raw_coordinates, list):
            coordinates.append(raw_coordinates)
        elif geometry_type == "LineString" and isinstance(raw_coordinates, list):
            coordinates.extend(
                coord for coord in raw_coordinates if isinstance(coord, list)
            )

    valid_coordinates: list[list[float]] = []
    for coord in coordinates:
        if len(coord) < 2:
            continue
        try:
            lng = float(coord[0])
            lat = float(coord[1])
        except (TypeError, ValueError):
            continue
        if -180 <= lng <= 180 and -90 <= lat <= 90:
            valid_coordinates.append([lng, lat])

    if not valid_coordinates:
        return {"latitude": 10.0, "longitude": 76.3, "zoom": 7}

    latitude = round(
        sum(coord[1] for coord in valid_coordinates) / len(valid_coordinates),
        4,
    )
    longitude = round(
        sum(coord[0] for coord in valid_coordinates) / len(valid_coordinates),
        4,
    )
    zoom = 9 if len(valid_coordinates) > 1 else 12
    return {"latitude": latitude, "longitude": longitude, "zoom": zoom}


MAX_AUTO_RESUMES = 10


def advance_graph(graph: Any, config: dict) -> Any:
    """Resume the parked graph until it actually needs user input, then return the snapshot.

    `interrupt_before=["n4_route"]` fires on *every* entry into N4 — the initial selection,
    N5 stop-removal replans, and N8 edit re-entries alike. Only the initial selection needs
    the user (the gallery); the other pauses carry `user_confirmed=True` and must flow
    through without re-showing the gallery. Naturally bounded (each N5 replan drops a stop;
    an edit re-enters N4 once), with MAX_AUTO_RESUMES as a hard backstop.
    """
    for _ in range(MAX_AUTO_RESUMES):
        snapshot = graph.get_state(config)
        if "n4_route" in tuple(snapshot.next) and snapshot.values.get("user_confirmed"):
            graph.invoke(None, config)
            continue
        return snapshot
    return graph.get_state(config)


@st.cache_resource
def get_graph() -> Any:
    return build_graph()


def thread_config() -> dict:
    return {"configurable": {"thread_id": st.session_state.thread_id}}


def current_snapshot() -> Any:
    return get_graph().get_state(thread_config())


def ensure_session_state() -> None:
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid.uuid4())
        # First run: N1 writes the greeting, the conditional edge routes to END,
        # and the thread waits for the first user message.
        get_graph().invoke(initial_trip_state(), thread_config())
    if "partial_demo_notice" not in st.session_state:
        st.session_state.partial_demo_notice = ""
    if "edit_in_flight" not in st.session_state:
        st.session_state.edit_in_flight = False


def render_chat(state: dict) -> None:
    for message in state.get("raw_messages", []):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])


def _compose_clarification_answer(selected: list[str], custom: str) -> str:
    """Merge picked options and free-text into one labeled answer for N1."""
    custom = custom.strip()
    parts: list[str] = []
    if selected:
        parts.append("Selected: " + ", ".join(selected) + ".")
    if custom:
        parts.append("Note: " + custom)
    return " ".join(parts).strip()


def render_clarification_options(state: dict) -> None:
    clarification = state.get("clarification_prompt", {})
    if not clarification or state.get("constraints"):
        return
    question = clarification.get("question", "")
    options = clarification.get("options", [])
    input_type = clarification.get("input_type", "single_select" if options else "text")
    allow_custom = clarification.get("allow_custom", True)

    with st.form("clarification_form", clear_on_submit=True):
        if question:
            st.markdown(f"**{question}**")

        selected: list[str] = []
        if input_type == "multi_select":
            for option in options:
                if st.checkbox(option, key=f"clarify_opt_{option}"):
                    selected.append(option)
        elif input_type == "single_select":
            choice = st.radio("Quick options:", options, index=None)
            if choice:
                selected.append(choice)

        custom = ""
        if allow_custom or input_type == "text":
            label = "Your answer:" if input_type == "text" else "Add anything else (optional):"
            custom = st.text_input(label)

        if st.form_submit_button("Select", use_container_width=True):
            answer = _compose_clarification_answer(selected, custom)
            if answer:
                handle_user_message(answer)
                st.rerun()


def handle_user_message(user_message: str) -> None:
    """Run one N1 turn on the graph thread; once constraints land, the same run
    continues through N2/N3 and parks at the N4 selection interrupt."""
    graph = get_graph()
    config = thread_config()
    state = graph.get_state(config).values
    messages = [
        *state.get("raw_messages", []),
        {"role": "user", "content": user_message},
    ]
    with st.spinner("Thinking through the trip constraints..."):
        graph.invoke({"raw_messages": messages}, config)
        advance_graph(graph, config)


def render_selection_gallery(state: dict) -> None:
    """Scrollable gallery of validated candidates, each a card with a checkbox for multi-select."""
    candidates = state.get("validated_candidates", [])
    if not candidates:
        st.info(destination_empty_message(state))
        return

    max_destinations = int(state.get("max_destinations", 3))
    st.subheader("Choose your stops")
    st.caption(f"Pick 1 to {max_destinations} places — Picnix chains them into one trip.")

    selected_indices: list[int] = []
    with st.container(height=420):
        for index, destination in enumerate(candidates):
            summary = destination_summary(destination)
            with st.container(border=True):
                checked = st.checkbox(summary["name"], key=f"select_dest_{index}")
                st.caption(f"📍 {summary['distance']}  ·  🕒 {summary['duration']}")
                st.write(summary["description"])
                for note in summary["notes"]:
                    st.info(note)
            if checked:
                selected_indices.append(index)

    over_limit = len(selected_indices) > max_destinations
    if over_limit:
        st.warning(
            f"Please pick at most {max_destinations} stops — you selected {len(selected_indices)}."
        )

    confirm_col, more_col = st.columns(2)
    confirm = confirm_col.button(
        "Confirm selection",
        use_container_width=True,
        disabled=not selected_indices or over_limit,
    )
    load_more = more_col.button("Load more options", use_container_width=True)

    if confirm:
        graph = get_graph()
        config = thread_config()
        with st.spinner("Building, validating, and writing the itinerary..."):
            # as_node="n3_validator" re-arms the thread even when it previously
            # reached END (the all-stops-dropped graceful failure path).
            graph.update_state(
                config,
                selection_updates(state, selected_indices),
                as_node="n3_validator",
            )
            graph.invoke(None, config)
            final_state = advance_graph(graph, config).values
        st.session_state.partial_demo_notice = (
            "Plan ready." if final_state.get("final_itinerary") else ""
        )
        st.rerun()

    if load_more:
        graph = get_graph()
        config = thread_config()
        with st.spinner("Validating more options..."):
            updated = load_more_candidates(state)
        graph.update_state(
            config,
            {
                "candidate_index": updated.get("candidate_index", 0),
                "validated_candidates": updated.get("validated_candidates", []),
                "validation_failures": updated.get("validation_failures", []),
            },
            as_node="n3_validator",
        )
        st.rerun()


def render_plan(state: dict) -> None:
    """Render the confirmed multi-stop itinerary, route metrics, timeline, and food."""
    if st.session_state.partial_demo_notice:
        st.success(st.session_state.partial_demo_notice)

    final_itinerary = state.get("final_itinerary", "")
    if final_itinerary:
        st.subheader("Itinerary")
        st.markdown(final_itinerary)
        gmaps_link = generate_gmaps_link(state.get("timeline", []))
        if gmaps_link:
            st.link_button("Open in Google Maps 🗺️", url=gmaps_link)

    route = state.get("route", {})
    if route:
        st.divider()
        st.subheader("Route")
        route_cols = st.columns(2)
        route_cols[0].metric("Round trip", format_km(route.get("total_distance_meters")))
        route_cols[1].metric(
            "Planned duration",
            format_duration(route.get("planned_duration_seconds")),
        )
        rows = timeline_rows(state.get("timeline", []))
        if rows:
            st.table(rows)
        food_rows = food_availability_rows(state.get("food_availability", []))
        if food_rows:
            st.subheader("Food")
            st.table(food_rows)


def render_plan_editor(state: dict) -> None:
    """Edit box shown while the graph is parked before N8: submitting an edit resumes
    the thread through N8 → N4 → … → N7 and parks it here again with the new plan."""
    st.divider()
    st.subheader("Want to change anything?")
    with st.form("plan_edit_form", clear_on_submit=True):
        edit_instruction = st.text_input(
            "Want to change anything? Describe it.",
            placeholder="e.g. remove the waterfall, add the beach instead, leave at 7am",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button(
            "Update plan",
            use_container_width=True,
            disabled=st.session_state.edit_in_flight,
        )

    if submitted and edit_instruction.strip() and not st.session_state.edit_in_flight:
        st.session_state.edit_in_flight = True
        graph = get_graph()
        config = thread_config()
        try:
            with st.spinner("Reworking the plan..."):
                graph.update_state(
                    config,
                    {
                        "edit_instruction": edit_instruction.strip(),
                        "plan_edit_mode": True,
                    },
                )
                graph.invoke(None, config)
                final_state = advance_graph(graph, config).values
        finally:
            st.session_state.edit_in_flight = False
        st.session_state.partial_demo_notice = (
            "Plan updated." if final_state.get("final_itinerary") else ""
        )
        st.rerun()

    edit_history = state.get("edit_history", [])
    if edit_history:
        with st.expander(f"Edit history ({len(edit_history)})"):
            for entry in edit_history:
                stops = ", ".join(entry.get("resulting_destinations", [])) or "no stops"
                st.markdown(f"- **{entry.get('instruction', '')}** → {stops}")


def render_destination_panel(state: dict, next_nodes: tuple[str, ...]) -> None:
    """Dispatch the right panel off which node the graph is paused before."""
    removal_notice = state.get("removal_notice", "")
    if removal_notice:
        st.warning(removal_notice)

    if "n8_editor" in next_nodes:
        # Parked with the finished plan: itinerary + edit box. N8 rewrites
        # edit_notice every cycle, so a stale notice never carries over.
        edit_notice = state.get("edit_notice", "")
        if edit_notice:
            st.info(edit_notice)
        render_plan(state)
        render_plan_editor(state)
        return

    if "n4_route" in next_nodes:
        # advance_graph already consumed every confirmed pause, so this is the
        # initial (or post-removal re-selection) gallery.
        render_selection_gallery(state)
        return

    # Thread at END: intent phase, graceful failure, or the multiday dead end.
    if state.get("final_itinerary") and not state.get("route"):
        st.error(state["final_itinerary"])
    render_selection_gallery(state)


def render_trip_map(final_geojson: dict) -> None:
    features = final_geojson.get("features", [])
    if not features:
        st.info("The route map will appear after Picnix finishes the itinerary.")
        return

    mapbox_token = get_mapbox_token()
    if not mapbox_token:
        st.info("Set MAPBOX_TOKEN in .env to render the route map.")
        return

    pdk.settings.mapbox_api_key = mapbox_token
    center = final_geojson_center(final_geojson)
    layer = pdk.Layer(
        "GeoJsonLayer",
        final_geojson,
        pickable=True,
        stroked=True,
        filled=True,
        get_line_color=[41, 98, 255],
        get_fill_color=[230, 82, 82],
        get_radius=80,
        point_radius_min_pixels=7,
        line_width_min_pixels=4,
    )
    deck = pdk.Deck(
        map_style="mapbox://styles/mapbox/streets-v12",
        initial_view_state=pdk.ViewState(
            latitude=center["latitude"],
            longitude=center["longitude"],
            zoom=center["zoom"],
        ),
        layers=[layer],
        tooltip={
            "html": "<b>{label}</b><br/>{time}<br/>{notes}",
            "style": {"backgroundColor": "#1f2937", "color": "white"},
        },
    )
    st.pydeck_chart(deck, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="Picnix", layout="wide")
    ensure_session_state()

    snapshot = current_snapshot()
    state = dict(snapshot.values)
    next_nodes = tuple(snapshot.next)

    left, right = st.columns([0.4, 0.6])
    with left:
        st.title("Picnix")
        render_chat(state)
        render_clarification_options(state)
        if state.get("constraints"):
            st.caption("Constraints locked in — tweak the plan from the editor on the right.")
        elif user_message := st.chat_input(
            "Tell me your trip mood, starting point, time, and vehicle"
        ):
            handle_user_message(user_message)
            st.rerun()

    with right:
        st.title("Trip Preview")
        st.caption("Demo: N1 intent collection through N8 plan edits.")
        render_destination_panel(state, next_nodes)
        st.divider()
        render_trip_map(state.get("final_geojson", {}))


if __name__ == "__main__":
    main()
