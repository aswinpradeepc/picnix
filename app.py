from __future__ import annotations

from collections.abc import Callable

import pydeck as pdk
import streamlit as st

from graph.graph import (
    confirm_selection,
    initial_trip_state,
    load_more_candidates,
    run_candidate_discovery,
    run_final_formatter,
    run_intent_turn,
    run_itinerary_composer,
    run_route_builder,
    run_structured_validator,
)


MAX_REPLAN_ATTEMPTS = 3
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


def has_error_claims(state: dict) -> bool:
    return any(
        failure.get("severity") == "error"
        for failure in state.get("claim_failures", [])
        if isinstance(failure, dict)
    )


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


def run_confirmed_destination_pipeline(
    state: dict,
    *,
    route_runner: Callable[[dict], dict] = run_route_builder,
    validator_runner: Callable[[dict], dict] = run_structured_validator,
    composer_runner: Callable[[dict], dict] = run_itinerary_composer,
    formatter_runner: Callable[[dict], dict] = run_final_formatter,
) -> dict:
    """Build and validate the multi-stop route, dropping any unplannable stop and re-routing
    the remaining ones (N5 keeps `user_confirmed` true while stops survive), then compose."""
    next_state = state
    for _ in range(MAX_REPLAN_ATTEMPTS):
        next_state = route_runner(next_state)
        next_state = validator_runner(next_state)
        if not has_error_claims(next_state):
            break
        if not next_state.get("selected_destinations"):
            break
    if not next_state.get("selected_destinations") or has_error_claims(next_state):
        return next_state
    next_state = composer_runner(next_state)
    return formatter_runner(next_state)


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
    with st.spinner("Thinking through the trip constraints..."):
        st.session_state.graph_state = run_intent_turn(
            st.session_state.graph_state,
            user_message,
        )

    if st.session_state.graph_state.get("constraints") and not st.session_state.graph_state.get("candidates"):
        with st.spinner("Finding and validating destination candidates..."):
            st.session_state.graph_state = run_candidate_discovery(st.session_state.graph_state)


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
        confirmed_state = confirm_selection(state, selected_indices)
        with st.spinner("Building, validating, and writing the itinerary..."):
            st.session_state.graph_state = run_confirmed_destination_pipeline(confirmed_state)
        st.session_state.partial_demo_notice = (
            "Plan ready." if st.session_state.graph_state.get("final_itinerary") else ""
        )
        st.rerun()

    if load_more:
        with st.spinner("Validating more options..."):
            st.session_state.graph_state = load_more_candidates(state)
        st.rerun()


def render_plan(state: dict) -> None:
    """Render the confirmed multi-stop itinerary, route metrics, timeline, and food."""
    if st.session_state.partial_demo_notice:
        st.success(st.session_state.partial_demo_notice)

    final_itinerary = state.get("final_itinerary", "")
    if final_itinerary:
        st.subheader("Itinerary")
        st.markdown(final_itinerary)

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


def render_destination_panel() -> None:
    state = st.session_state.graph_state
    removal_notice = state.get("removal_notice", "")
    if removal_notice:
        st.warning(removal_notice)

    if state.get("user_confirmed") and state.get("route"):
        render_plan(state)
        return

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

    left, right = st.columns([0.4, 0.6])
    with left:
        st.title("Picnix")
        render_chat()
        render_clarification_options(st.session_state.graph_state)
        if user_message := st.chat_input("Tell me your trip mood, starting point, time, and vehicle"):
            handle_user_message(user_message)
            st.rerun()

    with right:
        st.title("Trip Preview")
        st.caption("Demo: N1 intent collection through N7 final itinerary output.")
        render_destination_panel()
        st.divider()
        render_trip_map(st.session_state.graph_state.get("final_geojson", {}))


if __name__ == "__main__":
    main()
