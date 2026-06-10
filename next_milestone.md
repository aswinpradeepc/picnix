# Picnix — next milestone Work Instructions

Read this file fully before touching any code. These are **sequential change sets**. Do not jump ahead. Complete each section, verify it works, then move to the next.

---

## Before You Start

1. Read `docs/design-context.md` in full.
2. Read `graph/state.py` — understand the full `TripState` schema.
3. Read `graph/graph.py` — understand the current node wiring and edges.
4. Read `docs/known-place-issues.md`.

---

## Change Set 0 — Create `agents.md` (do this first)

Create `agents.md` at the project root. This file is the shared north star for all agents (Claude Code, Codex, or any future agent) working on this project. It must be kept up to date as the project evolves.

Write `agents.md` with the following sections:

### `agents.md` required sections:

**Project identity**
- Name: Picnix
- Purpose: Conversational AI trip planner. Takes user constraints via chat, builds a time-accurate itinerary, renders it on a Mapbox map.
- Status: Active development. Single-user, local only. No auth, no billing, no production deployment yet.

**Tech stack** (copy from project brief — do not summarise, be exact)

**What is in scope right now**
- LangGraph AI graph (7 nodes + N8 plan editor, see Change Set 3)
- Streamlit UI
- Google Maps API integrations
- Mapbox rendering via pydeck

**What is explicitly out of scope — do not build these**
- FastAPI endpoints
- LangSmith / Arize observability tooling
- User authentication or session management
- Any database or persistent storage
- Production web frontend
- Docker / cloud deployment
- Token usage tracking

**File ownership map** — which concern lives where:
```
graph/state.py          — TripState schema. Change only when a node needs new fields.
graph/graph.py          — Node wiring, edges, interrupt config. Change when graph topology changes.
graph/nodes/            — One file per node. Each node owns its section of state.
tools/gmaps.py          — All Google Maps HTTP calls. No business logic here.
tools/mapbox.py         — Mapbox token helpers only.
config/settings.py      — All env var loading. No hardcoded strings elsewhere.
docs/known-place-issues.md — Durable place-level exceptions. Update here, not in node code.
agents.md               — This file. Update when scope, stack, or ownership changes.
```

**Current graph topology** (text description of node flow):
```
N1 (intent) → conditional edge → N2 (isochrone) → N3 (validator) →
[human interrupt] → N4 (route) → N5 (structured validator) →
N6 (composer) → N7 (formatter) → [human interrupt: plan editor] → N8 (plan editor) → N4
```

**Coding standards** (copy verbatim from project brief's "Coding standards" section)

**Change log** — append one line per completed change set:
```
| Date | Change Set | Summary |
|------|------------|---------|
```

---

## Change Set 1 — Graph visualisation utility

**Goal:** Make the compiled graph inspectable as a Mermaid diagram and PNG without running the full app.

**Steps:**

1. Add to `pyproject.toml` as optional dev dependency:
   ```
   pygraphviz  # optional, for PNG export
   ```

2. Create `tools/graph_viz.py`:
   ```python
   """
   Utility to export the compiled LangGraph as a Mermaid diagram and optionally a PNG.
   Called automatically in development mode (DEBUG=true in .env).
   Output: docs/graph.mmd and docs/graph.png (if pygraphviz available).
   """
   ```
   - Import the compiled graph from `graph/graph.py`
   - Call `graph.get_graph().draw_mermaid()` and write to `docs/graph.mmd`
   - Attempt `graph.get_graph().draw_mermaid_png()` — wrap in try/except, skip silently if pygraphviz is not installed
   - Write PNG to `docs/graph.png` if successful
   - Guard the whole function behind `settings.DEBUG == True`

3. Call `export_graph_diagram()` at the bottom of `graph/graph.py` inside a `if settings.DEBUG:` block, after the graph is compiled.

4. Add `docs/graph.mmd` and `docs/graph.png` to `.gitignore`.

5. Add `DEBUG=false` to `.env.example` with a comment: `# Set to true to export graph diagram to docs/ on startup`.

**Verify:** Run `DEBUG=true uv run streamlit run app.py` and confirm `docs/graph.mmd` is written.

---

**Change Set 2 — Intelligent dwell time via LLM**

**Goal:** Let the LLM decide dwell time per destination based on trip mood, group, and destination type — not a static lookup table.

**Files to change:** `graph/nodes/n4_route.py`

**Steps:**

In `n4_route.py`, before building the timeline, make a single lightweight LLM call to determine dwell time for each destination in `selected_destinations`:

Prompt the LLM with:
- Destination name, Google Places primary type, and any available description
- `group_size` and `vehicle` from constraints
- `interests` and `budget_feel` from constraints
- `duration_hours` total available
- Number of destinations selected

Ask it to return a JSON array: `[{"place_id": "...", "dwell_minutes": int, "reason": "string"}]`

The `reason` field is written into the `notes` of the corresponding `timeline` entry — useful for N6 and for debugging.

**Hard floor and ceiling (Python, not LLM):**
- Minimum dwell: 20 minutes (no destination gets less regardless of LLM output)
- Maximum dwell: `(duration_hours * 60 - estimated_total_travel_minutes) / num_destinations` — the LLM cannot exceed the mathematically available time
- Clamp the LLM output between these two bounds after receiving it

**N5 check:** - N5 should only flag if `dwell_minutes < 20` or if total dwell + travel exceeds `duration_hours * 60`.

**Do not change N3, N6, N7.**
---

## Change Set 3 — Structured clarification options in N1

**Goal:** N1 must emit structured clarification options (not plain prose questions) so the Streamlit UI can render them as radio buttons with a free-text fallback.

**Files to change:** `graph/state.py`, `graph/nodes/n1_intent.py`, `app.py`

**Steps:**

1. Add to `TripState` in `graph/state.py`:
   ```python
   clarification_prompt: dict  # {question: str, options: list[str], allow_custom: bool}
   ```

2. In `n1_intent.py`, when the node needs to ask a question:
   - Instead of returning a plain prose question, populate `clarification_prompt` with a structured dict
   - Example:
     ```python
     {
       "question": "What kind of trip are you in the mood for?",
       "options": ["Nature & outdoors", "Beach", "Cultural / heritage", "Food trail", "Long scenic ride"],
       "allow_custom": True
     }
     ```
   - Always set `allow_custom: True` — the user must always be able to type a freeform answer
   - Generate options from the `INTEREST_TYPE_MAP` keys in N2 — do not hardcode a separate list in N1

3. make ui changes aptly

**Do not change N2–N7.**

---

## Change Set 4 — Multi-destination selection

**Goal:** Allow users to select up to 3 destinations. N4 chains them into a single route.

This is the largest change. Read the full spec before starting.

**Files to change:** `graph/state.py`, `graph/nodes/n3_validator.py`, `graph/nodes/n4_route.py`, `graph/nodes/n5_validator.py`, `graph/nodes/n7_formatter.py`, `graph/graph.py`, `app.py`

**State changes** (`graph/state.py`):
- Rename `validated_destination: dict` → `selected_destinations: list[dict]` (max 3 items)
- Keep `validated_candidates: list[dict]` — this is still the queue N3 builds
- Add `max_destinations: int` — default 3, sourced from constraints or user selection
- Remove `presented_candidate_index` — replace with `presented_candidate_indices: list[int]` to track which candidates the user has already seen/rejected

**N3 changes** (`n3_validator.py`):
- No changes to validation logic
- Output still goes to `validated_candidates`
- N3 does not populate `selected_destinations` — that is set by the human interrupt

**Human interrupt changes** (`graph/graph.py` + `app.py`):
- The interrupt before N4 now shows `validated_candidates` as a checklist (multi-select), not a single card - you can keep this as a scrollable card gallery with checkbox in a corner - like ui
- User can select 1, 2, or 3 destinations
- Add a "Confirm selection" button — only active when at least 1 destination is selected
- On confirm: write the selected items to `selected_destinations`, set `user_confirmed = True`
- "Show me another" is replaced by "Load more options" — triggers N3 to validate more candidates from the raw pool

**N4 changes** (`n4_route.py`):
- Read `selected_destinations` (list) instead of `validated_destination` (dict)
- Build route as: `start → dest1 → dest2 → dest3 → start` using Google Routes API `computeRoutes` with intermediate waypoints
- Build a single unified `timeline` covering all stops in order
- `food_availability` decisions are made per destination segment, not globally

**N5 changes** (`n5_validator.py`):
- On error: remove the bad destination from `selected_destinations` (not `validated_candidates`). Convey to user why the destination they selected was removed.
- If `selected_destinations` becomes empty after removal, route to END with graceful message
- Update all Python checks to iterate over `selected_destinations`

**N7 changes** (`n7_formatter.py`):
- Emit one `Point` feature per destination in `selected_destinations`
- Route LineString covers the full multi-stop route
- Label each waypoint with destination index (Stop 1, Stop 2, Stop 3)

**Do not change N1, N2, N6.**

---

## Change Set 5 — Plan rework (N8 Plan Editor) — ✓ done, superseded by cs5.md v2

The original CS5 section that lived here had four ambiguities (conditional N7→N8, a
second "confirm the edit" interrupt, an undefined "request new validation" mechanism,
and no output contract for the N8 LLM call) and was replaced by the **`cs5.md` (v2)**
spec, which is the authoritative record of what was built: unconditional N7→N8 with a
park-at-`n8_editor` interrupt, closed-universe IDs-only edits, and an app-side
auto-resume rule for the N4 interrupt. Implemented 2026-06-10 on branch
`cs5-n8-plan-editor`; decisions recorded in `docs/adr/ADR-008-n8-plan-editor.md`.
On-demand validation of edit-requested places and user-directed food edits are
deferred as **FS-3** in `docs/future-scope.md`.

---

## Change Set 6 — Google Maps export link

**Goal:** After N7 completes, surface a Google Maps deep link the user can tap to navigate the full route.

**Files to change:** `tools/gmaps.py`, `app.py`

**Steps:**

1. Add to `tools/gmaps.py`:
   ```python
   def generate_gmaps_link(timeline: list[dict]) -> str:
       """
       Builds a Google Maps directions deep link from the trip timeline.
       Reads: timeline entries with coords (lat, lng).
       Returns: URL string for Google Maps multi-waypoint route.
       No API call. Pure URL construction.
       """
   ```
   - Extract the `coords` from the single `'start'` timeline entry → used as both origin and destination (round trip)
   - Extract `coords` from all `'destination'` timeline entries → used as waypoints
   - Build URL:
     ```
     https://www.google.com/maps/dir/?api=1
       &origin=<start lat,lng>
       &destination=<start lat,lng>
       &waypoints=<stop1 lat,lng>|<stop2 lat,lng>|...
       &travelmode=driving
     ```
   - Return the URL string (empty string if no start entry)

2. In `app.py`, after the final itinerary is rendered:
   - Call `generate_gmaps_link(state["timeline"])`
   - Render as `st.link_button("Open in Google Maps 🗺️", url=gmaps_link)`

**Do not add any API key to this URL. It is a free deep link.**

---

## Change Set 7 — Crisp bulleted itinerary format

**Goal:** Replace flowing prose in the itinerary with tight, scannable bullet sections.

**Files to change:** `graph/nodes/n6_composer.py`

**Steps:**

1. Replace the system prompt's format instruction (the last sentence before "After writing the prose...") with:
   ```
   Format: one bold section header per stop (e.g. **Morning · Start**, **Journey**, **Stop 1 — Place Name**, **Return**). 
   Under each header, write 3–5 bullet points. Each bullet is one fact, one sentence maximum. 
   No filler phrases, no transitions, no "you will". Be direct.
   ```

2. Keep all other system prompt content unchanged — especially the instruction to only use verified data and the Malayalam warmth instruction (which will be removed in Change Set 8).

3. Update the `prose` field description in the structured output schema docstring to reflect the new format.

**Do not change the claim_audit logic or any other part of N6.**

---

## Change Set 8 — Region agnostic

**Goal:** Remove all Kerala/India-specific elements so the planner works for any region.

**Files to change:** `graph/nodes/n6_composer.py`, `docs/known-place-issues.md`

**Steps:**

1. In `n6_composer.py` system prompt:
   - Remove: `"Use Malayalam words occasionally for warmth (e.g., "njan paranjaal" / "as I'd say", "kidu trip aakum!" / "it'll be a great trip!")`
   - Replace with: `"Use a warm, conversational, locally neutral tone. Be friendly but do not use region-specific phrases or local-language words."`
   - Keep everything else in the system prompt unchanged

2. In `docs/known-place-issues.md`:
   - Remove any rows that are specific to Kerala/India geography
   - Keep the schema (columns, format) intact
   - Add a comment at the top: `# This file is region-agnostic. Add durable place-level issues for any destination here.`

3. Search the entire codebase for the strings `Kerala`, `India`, `Malayalam`, `kochi`, `Kochi`, `Munnar`, `asia-south1` (in comments only — leave the actual env var value in `.env.example` as a comment noting it is an example).
   - Remove or generalise any found in code or prompts
   - `asia-south1` in `.env.example` should be changed to `<your-vertex-ai-region>` with a comment

4. Do **not** change `INTEREST_TYPE_MAP` in N2 — it is already region-agnostic.

---

## Completion Checklist

After all change sets are done:

- [ ] `agents.md` exists at project root and reflects current graph topology
- [ ] `docs/graph.mmd` is generated when `DEBUG=true`
- [ ] Dwell time cap is applied in N4 and checked in N5
- [ ] N1 emits `clarification_prompt` dict; Streamlit renders radio + text input
- [ ] Multi-destination selection works end to end (1–3 stops)
- [ ] N8 plan editor exists; user can add/remove stops after seeing the itinerary
- [ ] Google Maps link appears after final itinerary
- [ ] Itinerary is bulleted, not prose paragraphs
- [ ] No Kerala/India-specific strings remain in code or prompts
- [ ] `agents.md` change log is updated with all completed change sets
- [ ] All node functions have type hints and docstrings
- [ ] `uv run streamlit run app.py` starts without errors

---

## What NOT to do

- Do not add FastAPI, LangSmith, Arize, any database, or any auth system
- Do not add any new external API beyond Google Maps and Mapbox
- Do not modify `TripState` fields that are not mentioned in a change set
- Do not change N2's `INTEREST_TYPE_MAP`
- Do not commit `.env` — only `.env.example`
- Do not create `requirements.txt` — use `pyproject.toml` and `uv` only