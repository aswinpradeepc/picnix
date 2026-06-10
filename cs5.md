# Change Set 5 (v2) — N8 Plan Editor

Read this file fully before touching any code. This replaces the original CS5 section in `next_milestone.md`. If any implemented CS5 code exists from a previous attempt, **revert it first** and start from this spec — do not patch the old attempt.

---

## Before You Start

1. Read `agents.md`, `docs/adr/ADR-006-n5-n6-swap.md`, and `docs/adr/ADR-007-multi-destination-routing.md` in full. CS5 sits on top of the CS4 multi-destination state model — `selected_destinations: list[dict]`, `removal_notice`, `route_attempt_count` — not the old single-destination model.
2. Read `graph/graph.py` and identify: (a) where `interrupt_before=["n4_route"]` is configured, (b) the N5 conditional edge function, (c) how `app.py` currently detects "graph is paused before N4" and resumes it.
3. Read `app.py` end to end and write down (in your scratch notes) the current Streamlit state machine: which `st.session_state` keys decide which UI panel renders. You will be adding two new branches to this machine and a wrong guess here is the #1 source of bugs.
4. Read `graph/nodes/n6_composer.py` and note how the Gemini call enforces `response_schema` (the "N6 response missing prose" fix). N8 must use the same enforcement pattern.

---

## Goal

After the final itinerary is shown, the user can type a natural-language edit ("remove the waterfall", "add the beach instead", "leave at 7am") and the graph re-plans from N4 onward — without restarting the session and without ever being silently switched to places they didn't choose.

---

## Why the previous CS5 attempt was buggy (read this — it explains the design below)

The original CS5 spec had four ambiguities. Each one is resolved explicitly in this version:

1. **"N7 → N8 conditional on `plan_edit_mode`" is unimplementable as written.** When N7 first completes, `plan_edit_mode` is `False`, so the conditional edge routes to `END` — and once a LangGraph thread reaches `END`, there is nothing to resume into N8. The fix: N7 → N8 is an **unconditional edge**, and the graph **always pauses** via `interrupt_before=["n8_editor"]`. The pause itself is the "itinerary shown, awaiting possible edit" state. A user who is happy with the plan simply never resumes; the thread stays parked, which is fine for a local MemorySaver app.

2. **N8 → N4 collides with the existing `interrupt_before=["n4_route"]`.** `interrupt_before` is unconditional — it fires on *every* entry into N4, including the re-entry after an edit. The old spec set `user_confirmed = True` and assumed the graph would sail through; instead it pauses, and Streamlit shows the destination-selection gallery again mid-edit. The fix: a deterministic app-side auto-resume rule (Section "App state machine"), driven by `plan_edit_mode`, with N7 resetting the flag.

3. **"Search `validated_candidates` first before requesting new validation" — there is no mechanism to request new validation.** N8 has no edge to N3, and wiring one is a graph-topology change far beyond this change set. The fix: in CS5, additions are restricted to the already-validated pool. Anything outside it is reported back to the user as unfulfilled, never invented. Re-validation on demand is deferred as **FS-3**.

4. **No output contract for the N8 LLM call.** Freeform output meant the LLM sometimes returned destination dicts it composed itself (hallucinated coords, missing `place_id`s) or alias keys. The fix: N8's LLM returns **place IDs only**, selected from a closed set, under an enforced `response_schema`. Python maps IDs back to the real dicts. The LLM never authors a destination object.

---

## Design summary (decide-once, then implement)

```
... → N7 (formatter) → [interrupt: plan shown / edit box] → N8 (editor) → N4 → N5 → N6 → N7 → [interrupt again] → ...
```

- **One new node:** `graph/nodes/n8_editor.py`.
- **One new interrupt:** `interrupt_before=["n8_editor"]` added alongside the existing `n4_route` interrupt.
- **N7 → N8 unconditional.** No conditional edge out of N7. `END` is no longer reachable from N7; the only END paths remain N5's no-stops-left path and the multiday dead end.
- **Edits loop:** every edit re-runs N4 → N5 → N6 → N7 and parks at the N8 interrupt again. Multiple successive edits work for free.
- **N5's CS4 behavior is untouched.** If an edited plan doesn't fit, N5 drops a stop with `removal_notice` and re-plans exactly as it does today. The user sees the same removal re-prompt UI.

---

## State changes — `graph/state.py`

Add exactly these fields. Do not touch any other field.

```python
    # Set by app.py (edit submission) / reset by N7
    plan_edit_mode: bool        # True from edit submission until N7 completes the re-plan
    edit_instruction: str       # raw user edit text for the current edit; cleared by N8 after consuming

    # Set by N8
    edit_history: list[dict]    # [{instruction, timestamp, resulting_destinations, unfulfilled}]
    edit_notice: str            # user-facing message about what was/wasn't applied; "" when nothing to say
```

- `resulting_destinations` in `edit_history` stores the list of place **names** (not full dicts) for readability.
- `timestamp` is `datetime.now().isoformat()` — no new dependencies.
- Initialize all four in the same place existing state defaults are initialized (`plan_edit_mode=False`, `edit_instruction=""`, `edit_history=[]`, `edit_notice=""`).

---

## N8 node — `graph/nodes/n8_editor.py`

**Type:** LLM node (single call) + Python enforcement. Same shape as the CS2 dwell-time pattern: the LLM decides, Python clamps.

**Docstring contract:**
```
Reads from state:  edit_instruction, selected_destinations, validated_candidates,
                   constraints, max_destinations
Writes to state:   selected_destinations, constraints (timing fields only),
                   edit_history (appended), edit_notice, edit_instruction (cleared),
                   user_confirmed=True, route_attempt_count=0, removal_notice="",
                   route/timeline/food_stops/food_availability/claim_failures (reset)
```

### Step 1 — Build the candidate universe (Python)

```python
universe = {d["place_id"]: d for d in state["selected_destinations"]}
universe.update({c["place_id"]: c for c in state["validated_candidates"]})
```

This closed set is the **only** source of destinations the edited plan may contain.

### Step 2 — LLM call (one call, `gemini-2.5-pro` via `REASONING_GEMINI_MODEL`, enforced schema)

Prompt inputs:
- `edit_instruction`
- Current plan: ordered list of `{place_id, name, primary_type}` from `selected_destinations`
- Available alternatives: same shape, from `validated_candidates` not already selected
- Current `departure_time` and `duration_hours`
- `max_destinations`

**Required `response_schema`** (enforce with `response_mime_type="application/json"` **and** `response_schema`, exactly like the N6 fix — JSON mode alone is not enough):

```json
{
  "updated_place_ids": ["string"],          // ordered; subset of the provided IDs only
  "departure_time": "string|null",          // "HH:MM" only if the user asked to change it, else null
  "duration_hours": "number|null",          // only if the user asked to change it, else null
  "edit_summary": "string",                 // one sentence: what was applied
  "unfulfilled": [                          // requests that could not be applied
    {"request": "string", "reason": "string"}
  ]
}
```

Prompt rules (state these verbatim to the model):
- You may only use place IDs from the lists provided. If the user asks for a place or category not in the lists, do not invent one — put it in `unfulfilled` with reason "not in the validated pool for this trip".
- Keep at least 1 and at most `max_destinations` IDs. If the user asks to remove every stop, keep the list unchanged and add an `unfulfilled` entry suggesting they start a new plan.
- Preserve the existing order of stops you are not changing.
- If the instruction is purely a timing change, return `updated_place_ids` identical to the current plan.

### Step 3 — Python enforcement (never trust Step 2)

In order:
1. Drop any returned ID not in `universe`; map survivors to their full dicts.
2. If the result is empty or exceeds `max_destinations`, fall back to the **unchanged** `selected_destinations` and set `edit_notice` to an explanatory message. Never write an empty list — an empty list would trigger N5's END path and kill the session.
3. Validate `departure_time` matches `HH:MM`; validate `duration_hours` is a positive float ≤ 14 (the short-trip router bound). Reject invalid values, note in `edit_notice`. Apply valid ones to `constraints`.
4. Compose `edit_notice` from `edit_summary` + any `unfulfilled` reasons. If `duration_hours` changed, append: "Heads up — stops were validated for your original window; if something no longer fits, I'll drop it and tell you." (N5 enforces this; N8 does not re-validate.)
5. Append the `edit_history` entry.
6. Reset route artifacts so N4 builds fresh: `route={}`, `timeline=[]`, `food_stops=[]`, `food_availability=[]`, `claim_failures=[]`, `removal_notice=""`. Mirror whatever reset N5's CS4 replan path already does — copy that exact field list from `n5_validator.py` rather than guessing.
7. Set `user_confirmed=True`, `route_attempt_count=0`, clear `edit_instruction`.

Wrap the LLM call in try/except. On any exception or unparseable response: keep `selected_destinations` unchanged, set `edit_notice = "I couldn't apply that edit — try rephrasing it."`, still route to N4 (it will rebuild the same plan, which is harmless and keeps the graph in a consistent parked state).

---

## Graph wiring — `graph/graph.py`

1. Register `n8_editor`.
2. Edge `n7_formatter → n8_editor` (unconditional). Remove any `n7_formatter → END` edge.
3. Edge `n8_editor → n4_route` (unconditional).
4. Compile with `interrupt_before=["n4_route", "n8_editor"]`.
5. **N7 change (one line):** N7 additionally writes `plan_edit_mode = False` every time it completes. This is the deterministic reset that ends an edit cycle. Do not reset it anywhere else.

No other node changes. **Do not change N1, N2, N3, N6, and do not change N5's routing logic.**

---

## App state machine — `app.py`

This is where the previous attempt broke. Implement the interrupt dispatch as one explicit, ordered rule set. When the graph is paused, determine **which node it is paused before** (use `graph.get_state(config).next` — do not infer from your own session flags), then:

**Paused before `n4_route`** — three variants, checked in this order:
1. `removal_notice` is non-empty / `route_attempt_count > 0` → render the existing CS4 stop-removal re-prompt UI. (Unchanged behavior; takes precedence even during an edit cycle.)
2. `plan_edit_mode == True` → **auto-resume immediately.** Render nothing, call resume. This is the pass-through that lets an edit flow into N4 without re-showing the selection gallery.
3. Otherwise → the existing initial multi-select card gallery. (Unchanged.)

**Paused before `n8_editor`** — the "plan shown" state:
- Render the final itinerary + map (this already happens today after N7; the only difference is the graph is now parked rather than ended).
- If `edit_notice` is non-empty, render it as an info banner above the itinerary, then clear it from the local display state so it doesn't repeat on rerun.
- Below the itinerary, render `st.text_input("Want to change anything? Describe it.")` + a submit button.
- On submit:
  ```python
  graph.update_state(config, {"edit_instruction": text, "plan_edit_mode": True})
  # then resume the graph (same resume call used for the N4 interrupt)
  ```
- Guard against Streamlit double-submission: disable the button / clear the input via a session flag once a resume is in flight, re-enable when the graph parks again.

**Do not** add a separate "confirm the edit" interrupt between typing and N8. The submission *is* the confirmation; the old spec's extra confirm step added a second pause with no UI to drive it.

---

## Edge cases — implement and test each

| Case | Required behavior |
|---|---|
| "Remove all the stops" | Plan unchanged; `edit_notice` explains and suggests starting a new plan |
| "Add <place not in pool>" | Plan unchanged for that request; `unfulfilled` → `edit_notice` |
| "Add a 4th stop" when 3 selected | Clamped to `max_destinations`; `edit_notice` explains |
| "Leave at 7am" only | Same stops, new `departure_time`, full N4 re-plan |
| "Make it a 4-hour trip" when stops no longer fit | N8 applies it; N5 drops a stop with `removal_notice`; user sees the existing removal re-prompt |
| Edit while a previous edit's re-plan is mid-flight | Impossible by construction: edit box only renders when parked before N8 |
| LLM returns garbage / API error | Plan unchanged, `edit_notice` set, graph still parks cleanly at N8 again |
| Second and third successive edits | Each cycles N8→N4→…→N7→park; `edit_history` grows by one each time |

Unit tests (`tests/`): the Step 3 enforcement function must be a pure function (`apply_edit_result(llm_result, state) -> dict`) so it is testable with fixtures and a mocked LLM — test ID filtering, empty-list fallback, clamping, timing validation, and artifact reset. Add one graph-level test asserting the compiled graph's interrupt set and that N7 has no END edge.

---

## Docs to update on completion

- `agents.md`: change log row (CS5), graph topology block already shows N8 — verify it matches what you built (the brief's topology drawing showed the interrupt between N7 and N8; that is now exactly true).
- `docs/superpowers/status.md`: CS5 section.
- New `docs/adr/ADR-008-n8-plan-editor.md`: record (1) park-at-N8 interrupt model vs. conditional N7→END, (2) closed-universe edits with FS-3 deferral, (3) IDs-only LLM contract, (4) app-side auto-resume rule for the N4 interrupt. Add to the ADR README table.
- `docs/future-scope.md`: add **FS-3 — On-demand validation for edit-requested places** (N8 → N3 re-entry or a targeted single-place validation call, so "add Athirappilly" works when it isn't in the pool).

## What NOT to do

- Do not wire N8 → N3 or call any Google Maps API from N8. N8 is LLM + state surgery only.
- Do not let the LLM emit destination dicts, names-as-truth, or coordinates — IDs only.
- Do not add a second confirmation interrupt for edits.
- Do not modify N5's removal/replan logic or the CS4 selection gallery.
- Do not reset `plan_edit_mode` anywhere except N7.
- Do not write an empty `selected_destinations` from N8 under any circumstance.

## Verify

- [ ] Happy path: plan → "remove stop 2" → re-planned itinerary appears, gallery never reappears
- [ ] Add-from-pool: "swap the museum for the beach" works when the beach is in `validated_candidates`
- [ ] Out-of-pool add produces `edit_notice`, plan otherwise intact
- [ ] Timing-only edit re-plans with same stops
- [ ] Shrunk duration triggers N5 removal re-prompt UI (not the edit pass-through)
- [ ] Three edits in a row; `edit_history` has 3 entries
- [ ] `DEBUG=true` graph.mmd shows N7→N8→N4 and both interrupts
- [ ] `uv run pytest` passes; `uv run streamlit run app.py` starts clean