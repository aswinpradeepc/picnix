# Validated Suggestion Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fixed-size validated suggestion queue so users only cycle through destinations that passed N3 validation.

**Architecture:** N2 keeps a larger raw candidate pool, N3 fills a smaller validated queue, and Streamlit advances through the validated queue. Validation failures remain diagnostic state, not the main user-facing fallback.

**Tech Stack:** Python 3.13, uv, pytest, Streamlit, LangGraph-style state helpers, Google Maps tools.

---

### Task 1: Document State And Limits

**Files:**
- Modify: `design-context.md`
- Modify: `graph/state.py`
- Modify: `tests/test_state.py`

- [ ] Add `validated_candidates` and `presented_candidate_index` to `TripState`.
- [ ] Define fixed limits: `20` raw candidates and `5` validated suggestions.
- [ ] Update state tests to require the new fields.

### Task 2: Candidate Pool Fetching

**Files:**
- Modify: `graph/nodes/n2_isochrone.py`
- Modify: `tests/test_n2_isochrone.py`

- [ ] Write a failing test proving N2 requests `20` results per interest search and trims the ranked raw pool to `20`.
- [ ] Add constants for the raw pool and request size.
- [ ] Return an empty validated queue and reset the presented candidate cursor after each new discovery.

### Task 3: Validated Queue Construction

**Files:**
- Modify: `graph/graph.py`
- Modify: `graph/nodes/n3_validator.py`
- Modify: `tests/test_graph.py`
- Modify: `tests/test_n3_validator.py`

- [ ] Write failing tests proving validation continues until `5` valid suggestions are collected or the raw pool is exhausted.
- [ ] Change one-candidate validation so a successful candidate appends to `validated_candidates` and advances the raw cursor.
- [ ] Set `validated_destination` to the first validated queue item after queue construction.

### Task 4: User Rejection Flow

**Files:**
- Modify: `graph/graph.py`
- Modify: `app.py`
- Modify: `tests/test_graph.py`
- Modify: `tests/test_app_helpers.py`

- [ ] Write failing tests proving "Show me another" advances inside `validated_candidates` without appending user rejection to `validation_failures`.
- [ ] Make the no-more-options state a clean user message, not the validation failure list.
- [ ] Keep validation failures available only as diagnostics.

### Task 5: Verify And Commit

**Files:**
- All changed files from tasks above.

- [ ] Run targeted tests for graph, N2, N3, and app helpers.
- [ ] Run the full default pytest suite.
- [ ] Restart Streamlit on port `8501` and smoke check HTTP `200`.
- [ ] Commit the behavior change.
