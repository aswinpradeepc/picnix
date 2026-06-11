# Project Brief — Picnix (AI Core + Streamlit UI)

You are starting a greenfield Python project. Read this entire brief before writing a single line of code.

---

## What this is

A conversational AI trip planner for people who want to spend free time — a weekend, an evening, a day off — without having a plan. The system has a conversation with the user, figures out their constraints, picks a suitable destination, and builds a complete, time-accurate itinerary. It then renders that itinerary on a Mapbox map with waypoints, travel times, food stops, and notes.

This is a personal / non-commercial project. No monetisation or billing system yet. User accounts and persistence are now active scope under ADR-010.

---

## Scope for this build — UPDATED 2026-06-11

The original MVP build was limited to these two things:

1. **The AI layer** — a LangGraph graph with 7 nodes (described below)
2. **A Streamlit UI** — for testing the AI layer interactively, with a chat panel and a Mapbox map panel

The current milestone keeps the Streamlit app and LangGraph graph, and promotes backend authentication and persistence into active scope:

- PostgreSQL 15 in Docker Compose as the `db` service
- `streamlit-authenticator` for Streamlit registration/login
- PostgreSQL-backed LangGraph checkpointing
- strict 5 completed-trip trial limit per account

Do NOT build any of the following right now. Leave clean interfaces for them to be added later:
- FastAPI endpoints
- Token usage calculators or cost tracking
- A production web frontend
- LangSmith or Arize AX production observability tooling

---

## Tech stack

| Concern | Tool |
|---|---|
| AI graph | LangGraph (Python) |
| LLM | Google Vertex AI — use `gemini-2.5-flash` via `langchain-google-genai` (`ChatGoogleGenerativeAI`) |
| Map rendering | Mapbox GL JS, via `pydeck` in Streamlit |
| Place search & data | Google Maps Places API (New) |
| Routing & distance | Google Maps Routes API |
| POI access validation | Google Maps Places API — check opening hours, access details |
| UI framework | Streamlit |
| Config | `python-dotenv`, `.env` file for all keys |
| Package management | `uv`, with `pyproject.toml` and `uv.lock` |
| Persistence | PostgreSQL 15 |
| Authentication | `streamlit-authenticator` |

**No other external services.** No Overpass, no ORS, no OSRM, no OpenStreetMap API calls. Google Maps handles all geo data. Mapbox handles all rendering.

### Package management

Use `uv` for dependency management. `pyproject.toml` is the single source of truth for dependencies. Add dependencies with `uv add <package>`, commit `uv.lock`, and run the app with `uv run streamlit run app.py`. Do not create or use `requirements.txt`.

### Environment variables
```
GOOGLE_MAPS_API_KEY=
MAPBOX_TOKEN=
GOOGLE_CLOUD_PROJECT=        # your GCP project ID
GOOGLE_CLOUD_LOCATION=       # use asia-south1 for India/Mumbai Vertex AI
GOOGLE_APPLICATION_CREDENTIALS=  # optional; leave blank/unset for local ADC OAuth
```

For local development, authenticate Vertex AI with Application Default Credentials:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project <GOOGLE_CLOUD_PROJECT>
```

Do not set `GOOGLE_APPLICATION_CREDENTIALS` unless using a service account JSON. If it is set, Google auth checks that path before local ADC and can fail even when ADC is configured correctly.

### Required Google Cloud APIs

Enable these APIs in the same GCP project used by `.env`.

| API | Service name | Used by | Purpose |
|---|---|---|---|
| Places API (New) | `places.googleapis.com` | `tools/gmaps.py`, N2, N3, N4 | Destination search, place details, opening hours/access validation, food stop search |
| Geocoding API | `geocoding-backend.googleapis.com` | `tools/gmaps.py`, N2 | Convert user start-location text into latitude/longitude |
| Routes API | `routes.googleapis.com` | `tools/gmaps.py`, N3, N4 | Actual travel-time validation, round-trip route geometry, legs, ETAs |
| Vertex AI API | `aiplatform.googleapis.com` | `tools/vertex.py`, N1, N5, N6 | Gemini 2.5 Flash calls through `ChatGoogleGenerativeAI` using the Vertex AI backend |

Do not enable or use Maps JavaScript API, legacy Directions API, Distance Matrix API, Geolocation API, Time Zone API, Roads API, Overpass, ORS, OSRM, or OpenStreetMap API for this build.

### Internal tool surface

Keep external-service calls behind small functions so graph nodes do orchestration, not HTTP details.

| Tool function | Module | Nodes | External service |
|---|---|---|---|
| `geocode_location()` | `tools/gmaps.py` | N2 | Google Geocoding API |
| `build_reachable_area_polygon()` | `tools/gmaps.py` | N2 | Pure Python approximate GeoJSON polygon |
| `search_destinations_nearby()` | `tools/gmaps.py` | N2 | Google Places API (New) Nearby Search |
| `get_place_details()` | `tools/gmaps.py` | N3, N4 | Google Places API (New) Place Details |
| `compute_route()` | `tools/gmaps.py` | N3, N4 | Google Routes API `computeRoutes` |
| `search_food_stops_along_route()` | `tools/gmaps.py` | N4 | Google Places API (New), route-biased fallback search |
| `search_food_spots_near_location()` | `tools/gmaps.py` | N4 | Google Places API (New), restaurant/cafe search around dynamic route or destination coordinates |
| `validate_place_open_for_window()` | `tools/gmaps.py` | N3, N4 | Pure Python validation over Places opening-hours data |
| `maps_request()` | `tools/gmaps.py` | N2, N3, N4 | Shared Google Maps HTTP request/error handling |
| `get_mapbox_token()` / `require_mapbox_token()` | `tools/mapbox.py` | Streamlit UI | Local config helper for Mapbox rendering |
| `get_chat_model()` | `tools/vertex.py` | N1, N5, N6 | Vertex AI Gemini via `ChatGoogleGenerativeAI`, authenticated by ADC by default |

---

## LangGraph node architecture

The graph is a `StateGraph`. Every node reads from and writes to a shared `TripState` TypedDict. Define this state schema first, before any node code.

### TripState schema (define this first)

```python
class TripState(TypedDict):
    # Set by N1
    raw_messages: list[dict]          # full conversation history
    constraints: dict                 # structured JSON: start_location, departure_time,
                                      # duration_hours, group_size, vehicle, interests, budget_feel
    clarification_round: int          # how many question rounds have happened

    # Set by N2
    isochrone_polygon: dict           # GeoJSON polygon of reachable area
    candidates: list[dict]            # top 20 raw ranked destinations with coords, tags, distance
    candidate_index: int              # raw candidate cursor currently being validated

    # Set by N3
    validated_candidates: list[dict]  # up to 5 confirmed destinations with access/hours verified
    presented_candidate_index: int    # user-facing cursor inside validated_candidates
    validated_destination: dict       # current confirmed destination shown to the user
    validation_failures: list[str]    # diagnostic reasons raw candidates were rejected

    # Set by human interrupt
    user_confirmed: bool              # True = proceed; False means user has not accepted current suggestion

    # Set by N4
    route: dict                       # full route GeoJSON + ordered waypoints + ETAs
    food_stops: list[dict]            # validated food stops along route
    food_availability: list[dict]     # meal decisions: eat at destination, route options,
                                      # eat at home, or carry/parcel guidance
    timeline: list[dict]              # [{time, label, coords, type, notes}] ordered trip timeline

    # Set by N6
    itinerary_draft: str              # human-readable prose itinerary with inline self-check

    # Set by N5
    claim_failures: list[dict]        # [{field, issue, severity}] structured output validation issues from N5
    route_attempt_count: int          # how many times N5 has routed back to N4 with a different destination
    rewrite_count: int                # deprecated; retained for schema compatibility

    # Set by N7
    final_geojson: dict               # FeatureCollection for Mapbox rendering
    final_itinerary: str              # final validated prose
```

---

### N1 — Intent collector

**Type:** Conversational LLM node (no tool calls)

**Responsibility:** Have a friendly, short conversation to extract user constraints. Persona: warm and enthusiastic, like a friend who loves planning trips. Opening line style: *"Aah, sounds like you need a good day out! Let me help plan it. Tell me — where are you starting from, how much time do you have, and when do you want to leave?"*

**Rules:**
- Ask at most 3 questions across the entire conversation, grouped naturally
- Extract: `start_location` (text), `departure_time` (`HH:MM` 24-hour local time), `duration_hours` (float), `group_size` (int), `vehicle` (one of: `bike`, `car`, `public`, `none`), `interests` (list of strings), `budget_feel` (one of: `free`, `low`, `medium`, `splurge`)
- If `duration_hours` is missing, ask for it explicitly unless the 3-question limit is exhausted.
- If `departure_time` is missing, ask for it naturally with the other constraints unless the 3-question limit is exhausted.
- When enough info is gathered, output structured `constraints` dict to state and signal done
- If the user is vague and the 3-question limit is exhausted, make a reasonable assumption from the trip mood and state it, don't keep asking.
- Use `langchain_core.messages` for conversation history management

**Output:** `constraints` dict in state, `raw_messages` updated

---

### Conditional edge — trip type router

**Type:** Pure Python conditional edge (zero LLM cost)

```python
def route_trip_type(state: TripState) -> str:
    hours = state["constraints"]["duration_hours"]
    if hours <= 14:
        return "n2_isochrone"
    else:
        return "future_multiday"  # dead end node for now, just returns a message
```

Only the short jolly trip path (`<= 14 hours`) is implemented. The multiday path returns a friendly "coming soon" message.

---

### N2 — Isochrone + candidate fetch

**Type:** Tool-calling node

**Responsibility:** Given the start location and constraints, find a fixed raw pool of 20 ranked candidate destinations. These are not directly shown to the user until N3 validates them.

**Logic:**
1. Geocode `start_location` using Google Maps Geocoding API → get lat/lng
2. Calculate max one-way travel time: `(duration_hours - 2) / 2` hours (reserve 2 hrs at destination minimum)
3. Convert travel time to approximate radius in km based on vehicle type:
   - `bike`: 45 km/h avg → radius = travel_time_hrs * 45
   - `car`: 65 km/h avg → radius = travel_time_hrs * 65
   - `public`/`none`: 30 km/h avg → radius = travel_time_hrs * 30
4. Use Google Maps Places API (Nearby Search) to find candidate destinations within that radius, filtered by interest tags. Request 20 results per interest search, then dedupe locally.
5. Score and rank the top 20 raw candidates by: relevance to interests (keyword match on place types/name), distance fit (closer to max radius scores higher than too-near or too-far), Google rating.
6. Store the raw ranked pool as `candidates` in state. Reset `candidate_index`, `validated_candidates`, `presented_candidate_index`, and `validated_destination`.

**Interest → Google Places type mapping (hardcode this):**
```python
INTEREST_TYPE_MAP = {
    "nature": ["park", "tourist_attraction", "campground", "hiking_area", "nature_preserve", "scenic_spot"],
    "long_rides": ["tourist_attraction", "scenic_spot", "observation_deck"],
    "food": ["restaurant", "cafe", "meal_takeaway"],
    "beach": ["beach", "tourist_attraction"],
    "waterfall": ["tourist_attraction", "park", "hiking_area"],
    "hills": ["hiking_area", "park", "tourist_attraction"],
    "culture": ["museum", "art_gallery", "cultural_landmark", "historical_place", "hindu_temple", "church", "mosque"],
    "shopping": ["shopping_mall", "store"],
    "movies": ["movie_theater"],
}
```

Only use Google Places API (New) Nearby Search filter types in this mapping. Do not use response-only Table B types such as `natural_feature`, `point_of_interest`, or `place_of_worship` as `includedTypes`.

**Output:** `candidates` (list of up to 20 raw dicts), `candidate_index` = 0, `validated_candidates` = [], `presented_candidate_index` = 0, `validated_destination` = {}

---

### N3 — Destination validator

**Type:** Tool-calling node with retry loop

**Responsibility:** Validate raw candidates from `candidate_index` until the graph has a user-facing queue of 5 usable destinations or the raw pool is exhausted. Failed raw candidates remain diagnostic only.

**Checks to run (in order, stop on first failure):**
1. **Google Places Details call** — get opening hours, permanently closed flag, access info
2. **Is it open?** — check if the place is open during the trip window. If `permanently_closed: true` → fail.
3. **Opening hours match** — if the trip is on a weekend and the place is closed weekends → fail
4. **Travel time validation** — call Google Routes API for actual drive/ride time from start → destination. If actual time > `max_one_way_time * 1.3` → fail (accounts for traffic)
5. **Known place issue check** — read `docs/known-place-issues.md` and match by place name. If a matching row has action `reject`, fail validation and keep the destination out of `validated_candidates`. If a matching row has action `warn`, keep the destination but append the issue to `notes`.

Do not hardcode known restricted places inside prompts or Python node constants. Add durable edge cases to `docs/known-place-issues.md` so future agents can update the list when they discover reliable restrictions or recurring validation issues.

**Loop edge:** If validation fails → increment `candidate_index` → back to N3. If validation succeeds → append to `validated_candidates`, increment `candidate_index`, and continue until 5 validated suggestions exist or `candidate_index >= len(candidates)`.

**Output:** `validated_candidates` queue, `validated_destination` set to the first queue item, `validation_failures` list updated for diagnostics.

---

### Human-in-the-loop interrupt

**Type:** LangGraph `interrupt_before` on N4 — fires on initial destination selection and again after N5 rejects a destination.

**Initial interrupt (first run, `route_attempt_count == 0`):**

Before N4 runs, pause and surface to the Streamlit UI:
- The destination name, distance, travel time, and a one-sentence description
- Two buttons: **"Yes, plan this!"** and **"Show me another"**

If **"Show me another"**: advance `presented_candidate_index`, show the next item from `validated_candidates`. Do not add user rejections to `validation_failures`.
If **"Yes, plan this!"**: set `user_confirmed = True`, proceed to N4.

**Re-interrupt after N5 rejection (`route_attempt_count > 0`):**

N5 removes the bad destination from `validated_candidates`, resets `user_confirmed = False`, and routes back to N4. Because `interrupt_before=["n4_route"]` is always active, the graph pauses again before N4 can run. The Streamlit UI detects `route_attempt_count > 0` and shows a different prompt:
- An explanation: *"That destination couldn't be fully planned — here are the remaining options."*
- The updated, filtered `validated_candidates` list (rejected destination already removed)
- The same **"Yes, plan this!"** / **"Show me another"** buttons, now operating on the filtered list

The rejected destination is never shown again. The user makes an explicit new choice before N4 runs. N5 never silently switches the destination.

If `validated_candidates` is empty when N5 tries to route back, the graph terminates and shows a graceful failure: *"Couldn't build a workable plan for any nearby destination — try again with different preferences."*

In Streamlit, implement this using `st.session_state` and the LangGraph checkpoint/resume pattern. Use `state["route_attempt_count"] > 0` to distinguish the re-interrupt UI from the initial one.

---

### N4 — Route builder

**Type:** Tool-calling node

**Responsibility:** Build the actual route with real ETAs and find food stops.

**Logic:**
1. Get the full driving/biking route from start → destination → start using Google Routes API (round trip)
2. Extract waypoints, total distance, legs with step-by-step ETAs
3. Calculate the timeline:
   - Departure time comes from `constraints["departure_time"]`; do not hardcode a fixed default in N4
   - Add travel legs with real ETA from Routes API
   - Treat food as a first-class availability decision, not as an automatic restaurant stop
   - If the destination is food-oriented, satisfy requested meals at the destination instead of adding a separate food stop
   - If the user returns before or around a normal meal time and did not explicitly request outside food, mark that meal as `eat_at_home`
   - For explicit meal requests, search dynamically near the destination or sampled route segment where the user is expected to be during that meal window
   - For remote morning destinations, search dynamically near the outbound route segment; if food cannot be confirmed, add carry/parcel guidance
   - Allocate time at destination based on `duration_hours` minus travel and meal time, then cap destination dwell time by destination type so a single shrine, attraction, museum, or similar place does not consume the entire remaining trip window
   - Insert return journey with estimated arrival time
4. For each actual food need, call Google Maps Places API around dynamic coordinates derived from destination location or route geometry. Do not use static route towns, hubs, cities, or route checkpoints.
5. Validate food stop opening hours using Places Details

Food guidance can be one of: `eat_at_destination`, `destination_options`, `route_options`, `eat_at_home`, or `carry_or_parcel`.

**Output:** `route` (GeoJSON LineString + waypoints), `food_stops` list, `food_availability` list, `timeline` list

---

### N5 — Structured output validator

**Type:** Python + LLM node

**Responsibility:** Validate N4's structured output before prose is written. Guarantees the itinerary composer receives internally consistent, complete data. Runs two sequential passes: a rule-based Python structural pass, then an LLM semantic pass.

**Python checks (run first, in order, stop accumulating on error):**
1. **Timeline completeness** — every entry has non-empty `time`, `label`, `coords`, `type`, `notes`.
2. **Timeline ordering** — entries are in chronological order by `time`.
3. **Time arithmetic** — departure ≤ arrival at destination ≤ departure from destination ≤ return arrival.
4. **Route shape** — `route["geojson"]["geometry"]["coordinates"]` is a list with at least 2 points.
5. **Food coverage** — if constraints contain an explicit meal keyword, that meal appears in `food_availability`.
6. **Coords validity** — all `coords` dicts have `lat` in `[-90, 90]` and `lng` in `[-180, 180]`.

**LLM semantic pass (runs after Python checks):**
- Receives a structured summary of N4 output: timeline, food_availability, destination type, constraints.
- Checks for semantic inconsistencies that Python cannot catch: implausibly short or long dwell time at destination; a remote early-morning destination with no food guidance; food availability entries that contradict the destination type.
- Uses structured output to return a list: `[{"field": ..., "issue": ..., "severity": "warning" | "error"}]`.

**Routing logic (conditional edge out of N5):**

| Outcome | Condition | Action |
|---|---|---|
| `error` — candidates remain | `claim_failures` contains severity `"error"` AND `validated_candidates` is non-empty after removing the bad destination | Remove the rejected destination from `validated_candidates`. Reset `presented_candidate_index` to 0 and `validated_destination` to the first remaining candidate. Set `user_confirmed = False`. Increment `route_attempt_count`. Route to **N4** — `interrupt_before` fires again and the user picks from the filtered list. |
| `error` — no candidates remain | `claim_failures` contains severity `"error"` AND `validated_candidates` is now empty | Route to END with a graceful message: *"Couldn't build a workable plan for any nearby destination — try again with different preferences."* |
| `warning` only | No `"error"` entries; `"warning"` entries present | Fix minor issues in state directly where possible (re-order timeline, fill a missing field from available data). Pass remaining warnings in `claim_failures` to N6 as context. Route to **N6**. |
| Clean | `claim_failures` is empty | Route to **N6**. |

N5 never silently presents an error-flagged plan to N6 and never silently switches the destination. The re-interrupt is the mechanism that keeps the user in control of every destination change.

**Output:** `claim_failures` list; on error path additionally: `validated_candidates` (bad destination removed), `presented_candidate_index` reset to 0, `validated_destination` updated to first remaining, `user_confirmed` set to `False`, `route_attempt_count` incremented.

---

### N6 — Itinerary composer

**Type:** LLM-only node, structured output

**Responsibility:** Write the human-readable itinerary from N5-validated state. Uses a single structured LLM call that both composes prose and self-audits every factual claim in the same pass. No separate prose-validator node; no rewrite loop.

**Structured output schema the LLM must return:**
```json
{
  "prose": "string — the full itinerary text",
  "claim_audit": [
    {"claim": "string", "source_field": "string", "verified": true}
  ]
}
```

**Implementation requirement:** Configure the Gemini call with both
`response_mime_type="application/json"` and a `response_schema` matching the schema
above. JSON MIME mode alone only asks for JSON; it does not enforce exact keys such as
`prose`, and live responses may otherwise drift to aliases like `itinerary`.

**Process:**
1. Pass all N5-validated state to the LLM: `timeline`, `route`, `validated_destination`, `food_stops`, `food_availability`, and any `claim_failures` from N5.
2. The LLM composes prose and for every factual statement (place name, time, distance, food stop name) records the source state field and whether the value was found there.
3. Post-process: any claim with `verified: false` is stripped or rewritten to remove the unverifiable detail before writing `itinerary_draft`. The N5 `claim_failures` list is not modified.

**System prompt for this node (include verbatim):**
```
You are a friendly Kerala local trip planner. Write a warm, conversational trip itinerary 
based ONLY on the structured data provided. Do not invent any place names, travel times, 
distances, or facts not present in the input data. Use Malayalam words occasionally for 
warmth (e.g., "njan paranjaal" / "as I'd say", "kidu trip aakum!" / "it'll be a great trip!"). 
Format: a flowing paragraph per section (morning, journey, destination, return), not bullet points.
After writing the prose, list every factual claim with its source field from the input data and 
whether it is verified (true/false). Return the result as the structured JSON schema given.
```

**Output:** `itinerary_draft` string (only verified claims retained)

---

### N7 — GeoJSON formatter + final output

**Type:** Pure Python node, no LLM

**Responsibility:** Convert verified state data into structured output for Mapbox rendering.

**Output structure:**
```python
final_geojson = {
    "type": "FeatureCollection",
    "features": [
        # LineString for the route
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [...]},
         "properties": {"type": "route"}},
        # Point for each waypoint (start, food stop, destination, return)
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lng, lat]},
         "properties": {"type": "waypoint", "label": "...", "time": "...", "notes": "..."}}
    ]
}
```

Reads `route` and `timeline` from state (both written by N4) to produce the GeoJSON features. Copies `itinerary_draft` (written by N6) to `final_itinerary`. This is the node that Streamlit reads from.

---

## Streamlit UI spec

Two-column layout:
- **Left column (40%):** Chat interface. Shows conversation history. Text input at bottom. When the human interrupt fires, show the destination card with Yes/Another buttons.
- **Right column (60%):** `pydeck` map with Mapbox tiles. After N7 completes, render the route LineString and waypoint markers. Clicking a marker shows the timeline entry for that stop in a tooltip.

Use `st.session_state` for:
- `graph_state` — the current LangGraph state dict
- `thread_id` — for LangGraph checkpointing
- `messages` — displayed chat history

Keep the UI code in `app.py`. Keep all graph/node code in `graph/` directory. Keep all tool functions in `tools/` directory.

---

## Project structure

```
picnix/
├── .env                    # API keys — never commit
├── .env.example            # template with key names, no values
├── .gitignore
├── pyproject.toml          # project metadata and dependencies
├── uv.lock                 # locked dependency graph
├── app.py                  # Streamlit entry point
├── graph/
│   ├── __init__.py
│   ├── state.py            # TripState TypedDict — define first
│   ├── graph.py            # StateGraph definition, edges, compile
│   └── nodes/
│       ├── __init__.py
│       ├── n1_intent.py
│       ├── n2_isochrone.py
│       ├── n3_validator.py
│       ├── n4_route.py
│       ├── n5_validator.py
│       ├── n6_composer.py
│       └── n7_formatter.py
├── tools/
│   ├── __init__.py
│   ├── gmaps.py            # all Google Maps API calls
│   └── mapbox.py           # Mapbox token config helpers
├── config/
│   ├── __init__.py
│   └── settings.py         # load .env, export constants
└── tests/
    ├── test_state.py
    ├── test_tools.py
    └── fixtures/           # sample state dicts for node unit tests
```

---

## What to build first (strict order)

1. `graph/state.py` — TripState TypedDict. Nothing else until this is reviewed.
2. `config/settings.py` + `.env.example` — load keys, verify connections
3. `tools/gmaps.py` — all Google Maps wrapper functions (geocode, places search, routes, place details). Unit test each independently with real API calls in `tests/test_tools.py`.
4. Node by node: N1 → N2 → N3 → N4 → N5 → N6 → N7. Test each node in isolation with a hardcoded state fixture before wiring into the graph.
5. `graph/graph.py` — wire all nodes, define edges, add interrupt
6. `app.py` — Streamlit UI

---

## Future scope — do not build, just leave clean interfaces

### Technical (infrastructure)
- FastAPI layer wrapping the graph for external API consumers
- LangSmith integration for tracing and prompt debugging
- Token usage tracking per graph run
- User accounts and trip history persistence (PostgreSQL)
- Production web frontend (React or Next.js)
- Docker + cloud deployment (Cloud Run on GCP makes sense given Vertex AI)

### Feature (product)
- Multi-day tour planning flow (separate graph, different node set)
- Movie and event integration (BookMyShow / KPAC / Google Events)
- Real-time traffic-aware routing (Google Maps Traffic model)
- User preference history ("don't suggest places I've been")
- Zomato/Swiggy integration for food stop reservation links
- Budget estimation with per-stop cost breakdown
- WhatsApp share link for the final itinerary

---

## Coding standards

- All node functions must have type hints and a one-paragraph docstring explaining what they read from state and what they write to state
- All Google Maps API calls must be wrapped in try/except with explicit error messages — never let an API failure crash the graph silently
- No hardcoded strings outside of `config/settings.py` and the interest→type map in N2
- The LangGraph graph must be compiled with a `MemorySaver` checkpointer from day one — this is required for the human interrupt to work
- Use `python-dotenv` and never reference `os.environ` directly — always go through `config/settings.py`

---
