from __future__ import annotations

import uuid
from typing import Any

import pydeck as pdk
import streamlit as st
import streamlit_authenticator as stauth

from observability.bootstrap import configure_observability

configure_observability()

from config.settings import SETTINGS
from graph.graph import (
    build_graph,
    initial_trip_state,
    load_more_candidates,
    selection_updates,
)
from persistence.database import (
    PlanHistoryItem,
    TRIAL_LIMIT,
    create_connection_pool,
    create_postgres_checkpointer,
    create_user,
    get_trips_planned,
    has_trial_capacity,
    initialize_picnix_schema,
    list_plan_history,
    load_auth_credentials,
    mark_trip_completed,
    normalize_username,
    update_last_login,
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
MAX_HISTORY_ITEMS = 20
PLAN_WIDGET_KEY_PREFIXES = ("select_dest_", "clarify_opt_")


def validate_signup_fields(
    username: str,
    email: str,
    password: str,
    password_repeat: str,
) -> list[str]:
    """Return user-facing validation errors for the DB-backed sign-up form."""
    errors: list[str] = []
    normalized_username = normalize_username(username)
    normalized_email = email.strip().lower()
    if len(normalized_username) < 3:
        errors.append("Username must be at least 3 characters.")
    if not normalized_username.replace("_", "").replace("-", "").isalnum():
        errors.append("Username can only contain letters, numbers, hyphens, and underscores.")
    if "@" not in normalized_email or "." not in normalized_email.rsplit("@", 1)[-1]:
        errors.append("Enter a valid email address.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if password != password_repeat:
        errors.append("Passwords do not match.")
    return errors


def _compact_text(value: str, *, max_length: int = 72) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 3].rstrip() + "..."


def _destination_names(state: dict) -> list[str]:
    destinations = state.get("selected_destinations", [])
    if not isinstance(destinations, list):
        return []
    return [
        str(destination.get("name", "")).strip()
        for destination in destinations
        if isinstance(destination, dict) and str(destination.get("name", "")).strip()
    ]


def plan_history_title(state: dict) -> str:
    constraints = state.get("constraints", {})
    start_location = ""
    if isinstance(constraints, dict):
        start_location = str(constraints.get("start_location", "")).strip()
    destination_names = _destination_names(state)

    if destination_names:
        destination_text = ", ".join(destination_names[:2])
        if len(destination_names) > 2:
            destination_text = f"{destination_text} + {len(destination_names) - 2} more"
        if start_location:
            return _compact_text(f"{start_location} to {destination_text}")
        return _compact_text(destination_text)
    if start_location:
        return _compact_text(f"Trip from {start_location}")
    return "Untitled plan"


def plan_history_summary(state: dict) -> dict[str, Any]:
    constraints = state.get("constraints", {})
    route = state.get("route", {})
    safe_constraints = constraints if isinstance(constraints, dict) else {}
    safe_route = route if isinstance(route, dict) else {}
    return {
        "start_location": safe_constraints.get("start_location", ""),
        "duration_hours": safe_constraints.get("duration_hours"),
        "vehicle": safe_constraints.get("vehicle", ""),
        "interests": safe_constraints.get("interests", []),
        "destinations": _destination_names(state),
        "total_distance_meters": safe_route.get("total_distance_meters"),
        "planned_duration_seconds": safe_route.get("planned_duration_seconds"),
    }


def _format_completed_at(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%b %d, %Y %H:%M")
    return str(value or "").strip()


def plan_history_caption(item: PlanHistoryItem) -> str:
    summary = item.plan_summary or {}
    parts: list[str] = []
    completed_at = _format_completed_at(item.completed_at)
    if completed_at:
        parts.append(completed_at)
    destinations = summary.get("destinations", [])
    if isinstance(destinations, list) and destinations:
        parts.append(f"{len(destinations)} stop{'s' if len(destinations) != 1 else ''}")
    distance = summary.get("total_distance_meters")
    if distance:
        parts.append(format_km(distance))
    duration = summary.get("planned_duration_seconds")
    if duration:
        parts.append(format_duration(duration))
    return " · ".join(parts) or "Completed plan"


def is_completed_plan_snapshot(snapshot: Any) -> bool:
    """A graph run has finished N7 when it is parked before N8 with final output present."""
    return (
        "n8_editor" in tuple(snapshot.next)
        and bool(snapshot.values.get("final_itinerary"))
        and bool(snapshot.values.get("final_geojson"))
    )


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
def get_database_pool() -> Any:
    pool = create_connection_pool()
    initialize_picnix_schema(pool)
    return pool


@st.cache_resource
def get_graph() -> Any:
    return build_graph(checkpointer=create_postgres_checkpointer(get_database_pool()))


def build_authenticator(credentials: dict) -> stauth.Authenticate:
    return stauth.Authenticate(
        credentials,
        SETTINGS.auth_cookie_name,
        SETTINGS.auth_cookie_key,
        SETTINGS.auth_cookie_expiry_days,
        auto_hash=False,
    )


def authenticated_username() -> str:
    return normalize_username(str(st.session_state.get("username") or ""))


def graph_execution_allowed(username: str) -> bool:
    if has_trial_capacity(get_database_pool(), username):
        return True
    st.session_state.limit_reached_notice = (
        "Limit reached: this account has used all 5 completed trip plans."
    )
    return False


def _clear_plan_widget_state() -> None:
    for key in list(st.session_state.keys()):
        if str(key).startswith(PLAN_WIDGET_KEY_PREFIXES):
            st.session_state.pop(key, None)


def _synced_completed_threads() -> set[str]:
    if "synced_completed_threads" not in st.session_state:
        st.session_state.synced_completed_threads = set()
    return st.session_state.synced_completed_threads


def _reset_plan_session(thread_id: str) -> None:
    st.session_state.thread_id = thread_id
    st.session_state.partial_demo_notice = ""
    st.session_state.edit_in_flight = False
    st.session_state.limit_reached_notice = ""
    _clear_plan_widget_state()


def start_new_plan_thread() -> None:
    _reset_plan_session(str(uuid.uuid4()))
    get_graph().invoke(initial_trip_state(), thread_config())


def load_plan_thread(thread_id: str) -> None:
    _reset_plan_session(thread_id)


def record_completed_trip_if_ready(username: str, snapshot: Any) -> None:
    if not is_completed_plan_snapshot(snapshot):
        return
    thread_id = st.session_state.thread_id
    synced_threads = _synced_completed_threads()
    if thread_id in synced_threads:
        return
    state = dict(snapshot.values)
    if mark_trip_completed(
        get_database_pool(),
        username=username,
        thread_id=thread_id,
        title=plan_history_title(state),
        plan_summary=plan_history_summary(state),
        final_itinerary=str(state.get("final_itinerary") or ""),
    ):
        st.session_state.partial_demo_notice = "Plan ready."
    synced_threads.add(thread_id)


def thread_config() -> dict:
    return {"configurable": {"thread_id": st.session_state.thread_id}}


def current_snapshot() -> Any:
    return get_graph().get_state(thread_config())


def sync_authenticated_user(username: str) -> None:
    if st.session_state.get("authenticated_username") == username:
        return
    st.session_state.authenticated_username = username
    for key in (
        "thread_id",
        "partial_demo_notice",
        "edit_in_flight",
        "limit_reached_notice",
        "synced_completed_threads",
    ):
        st.session_state.pop(key, None)


def ensure_session_state() -> None:
    if "thread_id" not in st.session_state:
        start_new_plan_thread()
    if "partial_demo_notice" not in st.session_state:
        st.session_state.partial_demo_notice = ""
    if "edit_in_flight" not in st.session_state:
        st.session_state.edit_in_flight = False
    if "limit_reached_notice" not in st.session_state:
        st.session_state.limit_reached_notice = ""


def render_signup_form() -> None:
    with st.form("signup_form", clear_on_submit=True):
        st.subheader("Sign Up")
        username = st.text_input("Username", autocomplete="username")
        email = st.text_input("Email", autocomplete="email")
        password = st.text_input("Password", type="password", autocomplete="new-password")
        password_repeat = st.text_input(
            "Repeat password",
            type="password",
            autocomplete="new-password",
        )
        submitted = st.form_submit_button("Create account", use_container_width=True)

    if not submitted:
        return

    errors = validate_signup_fields(username, email, password, password_repeat)
    if errors:
        for error in errors:
            st.error(error)
        return

    password_hash = stauth.Hasher.hash(password)
    created = create_user(
        get_database_pool(),
        username=username,
        email=email,
        password_hash=password_hash,
    )
    if not created:
        st.error("That username or email is already registered.")
        return
    st.success("Account created. Log in to start planning.")


def render_auth_gate() -> tuple[str, stauth.Authenticate] | None:
    credentials = load_auth_credentials(get_database_pool())
    authenticator = build_authenticator(credentials)

    if st.session_state.get("authentication_status"):
        username = authenticated_username()
        if username in credentials.get("usernames", {}):
            update_last_login(get_database_pool(), username)
            return username, authenticator
        st.session_state.authentication_status = None
        st.session_state.username = ""

    st.title("Picnix")
    login_tab, signup_tab = st.tabs(["Login", "Sign Up"])
    with login_tab:
        try:
            authenticator.login(
                location="main",
                max_login_attempts=5,
                clear_on_submit=True,
            )
        except Exception as exc:
            st.error(str(exc))

        auth_status = st.session_state.get("authentication_status")
        if auth_status is False:
            st.error("Username/password is incorrect.")
        elif auth_status is None:
            st.info("Log in or create an account to plan trips.")

    with signup_tab:
        render_signup_form()

    if st.session_state.get("authentication_status"):
        st.rerun()
    return None


def render_limit_reached(trips_planned: int) -> None:
    st.title("Limit Reached")
    st.info(
        f"This account has completed {trips_planned}/{TRIAL_LIMIT} trip plans. "
        "Start a new account to continue testing Picnix."
    )


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
    username = authenticated_username()
    if not graph_execution_allowed(username):
        return
    graph = get_graph()
    config = thread_config()
    state = graph.get_state(config).values
    messages = [
        *state.get("raw_messages", []),
        {"role": "user", "content": user_message},
    ]
    with st.spinner("Thinking through the trip constraints..."):
        graph.invoke({"raw_messages": messages}, config)
        snapshot = advance_graph(graph, config)
        record_completed_trip_if_ready(username, snapshot)


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
    limit_reached = not has_trial_capacity(get_database_pool(), authenticated_username())
    if limit_reached:
        st.caption("Trial limit reached — destination planning is disabled for this account.")

    confirm_col, more_col = st.columns(2)
    confirm = confirm_col.button(
        "Confirm selection",
        use_container_width=True,
        disabled=not selected_indices or over_limit or limit_reached,
    )
    load_more = more_col.button(
        "Load more options",
        use_container_width=True,
        disabled=limit_reached,
    )

    if confirm:
        username = authenticated_username()
        if not graph_execution_allowed(username):
            st.rerun()
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
            snapshot = advance_graph(graph, config)
            record_completed_trip_if_ready(username, snapshot)
            final_state = snapshot.values
        st.session_state.partial_demo_notice = (
            "Plan ready." if final_state.get("final_itinerary") else ""
        )
        st.rerun()

    if load_more:
        username = authenticated_username()
        if not graph_execution_allowed(username):
            st.rerun()
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
    limit_reached = not has_trial_capacity(get_database_pool(), authenticated_username())
    if limit_reached:
        st.caption("Trial limit reached — plan editing is disabled for this account.")
    with st.form("plan_edit_form", clear_on_submit=True):
        edit_instruction = st.text_input(
            "Want to change anything? Describe it.",
            placeholder="e.g. remove the waterfall, add the beach instead, leave at 7am",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button(
            "Update plan",
            use_container_width=True,
            disabled=st.session_state.edit_in_flight or limit_reached,
        )

    if submitted and edit_instruction.strip() and not st.session_state.edit_in_flight:
        username = authenticated_username()
        if not graph_execution_allowed(username):
            st.rerun()
        _synced_completed_threads().discard(st.session_state.thread_id)
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
                snapshot = advance_graph(graph, config)
                record_completed_trip_if_ready(username, snapshot)
                final_state = snapshot.values
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


def render_account_sidebar(
    *,
    username: str,
    authenticator: stauth.Authenticate,
    trips_planned: int,
) -> None:
    with st.sidebar:
        st.caption(f"Signed in as {username}")
        st.progress(min(trips_planned, TRIAL_LIMIT) / TRIAL_LIMIT)
        st.caption(f"{min(trips_planned, TRIAL_LIMIT)}/{TRIAL_LIMIT} completed trips")
        st.divider()

        can_start_plan = trips_planned < TRIAL_LIMIT
        if st.button(
            "New plan",
            use_container_width=True,
            disabled=not can_start_plan,
        ):
            start_new_plan_thread()
            st.rerun()
        if not can_start_plan:
            st.caption("Trial limit reached — previous plans remain available.")

        st.subheader("Previous plans")
        history = list_plan_history(
            get_database_pool(),
            username,
            limit=MAX_HISTORY_ITEMS,
        )
        if not history:
            st.caption("Completed plans will appear here.")
        for item in history:
            is_current = st.session_state.get("thread_id") == item.thread_id
            if st.button(
                item.title,
                key=f"history_{item.thread_id}",
                help=plan_history_caption(item),
                use_container_width=True,
                disabled=is_current,
            ):
                load_plan_thread(item.thread_id)
                st.rerun()
            st.caption(plan_history_caption(item))

        st.divider()
        authenticator.logout("Logout", location="sidebar", key="picnix_logout")


def main() -> None:
    st.set_page_config(page_title="Picnix", layout="wide")

    auth_context = render_auth_gate()
    if auth_context is None:
        return

    username, authenticator = auth_context
    sync_authenticated_user(username)

    trips_planned = get_trips_planned(get_database_pool(), username)
    if "thread_id" not in st.session_state and trips_planned >= TRIAL_LIMIT:
        render_account_sidebar(
            username=username,
            authenticator=authenticator,
            trips_planned=trips_planned,
        )
        render_limit_reached(trips_planned)
        return

    ensure_session_state()

    snapshot = current_snapshot()
    record_completed_trip_if_ready(username, snapshot)
    trips_planned = get_trips_planned(get_database_pool(), username)
    state = dict(snapshot.values)
    next_nodes = tuple(snapshot.next)

    render_account_sidebar(
        username=username,
        authenticator=authenticator,
        trips_planned=trips_planned,
    )

    left, right = st.columns([0.4, 0.6])
    with left:
        st.title("Picnix")
        if st.session_state.limit_reached_notice:
            st.warning(st.session_state.limit_reached_notice)
        render_chat(state)
        if trips_planned >= TRIAL_LIMIT:
            st.caption("Trial limit reached — graph execution is disabled for this account.")
        else:
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
