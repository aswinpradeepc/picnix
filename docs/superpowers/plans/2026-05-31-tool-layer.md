# Tool Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the reusable external-service wrappers for Google Maps, Mapbox, and Vertex AI before node implementation.

**Architecture:** Keep graph nodes free of raw HTTP and SDK setup. `tools/gmaps.py` owns Google Maps HTTP calls and response normalization, `tools/mapbox.py` owns Mapbox token access, and `tools/vertex.py` owns Gemini model construction through `ChatGoogleGenerativeAI` using Vertex AI ADC.

**Tech Stack:** Python 3.13, uv, pytest, requests, python-dotenv, Google Maps Platform APIs, Mapbox, `langchain-google-genai`.

---

### Task 1: Update LLM Dependency And Project Bible

**Files:**
- Modify: `design-context.md`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Add the replacement dependency**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv add langchain-google-genai`

Expected: `pyproject.toml` includes `langchain-google-genai`.

- [ ] **Step 2: Remove deprecated dependency**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv remove langchain-google-vertexai`

Expected: `pyproject.toml` no longer includes `langchain-google-vertexai`.

- [ ] **Step 3: Update design-context wording**

Replace `ChatVertexAI` references with `ChatGoogleGenerativeAI`, keeping Vertex AI as the backend and ADC as the authentication method.

### Task 2: Write Tool Tests First

**Files:**
- Create: `tests/test_tools.py`

- [ ] **Step 1: Write tests for Mapbox token helpers**

Assert `get_mapbox_token()` returns configured token and `require_mapbox_token()` raises for blank values.

- [ ] **Step 2: Write tests for Vertex model construction**

Assert `get_chat_model()` returns a `ChatGoogleGenerativeAI` instance configured with model, project, location, and Vertex backend.

- [ ] **Step 3: Write tests for Google Maps response normalization**

Assert geocoding, nearby place search, place details, route response parsing, polygon creation, and opening-hour validation work from deterministic fake responses.

- [ ] **Step 4: Write opt-in live tests**

Add tests skipped unless `PICNIX_RUN_LIVE_TESTS=1`, covering one Geocoding, one Nearby Search, one Routes API, one Mapbox style lookup, and one Vertex model call.

### Task 3: Implement Tool Modules

**Files:**
- Create: `tools/gmaps.py`
- Create: `tools/mapbox.py`
- Create: `tools/vertex.py`
- Modify: `tools/__init__.py`

- [ ] **Step 1: Run tool tests to verify red**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv run pytest tests/test_tools.py -v`

Expected: FAIL because tool modules are not implemented.

- [ ] **Step 2: Implement `tools/mapbox.py`**

Add token helpers that read `Settings`, return strings, and raise clear configuration errors for missing token values.

- [ ] **Step 3: Implement `tools/vertex.py`**

Add `get_chat_model()` that uses `ChatGoogleGenerativeAI(model="gemini-2.5-flash", project=..., location=..., vertexai=True)`.

- [ ] **Step 4: Implement `tools/gmaps.py`**

Add `maps_request()`, `geocode_location()`, `build_reachable_area_polygon()`, `search_destinations_nearby()`, `get_place_details()`, `compute_route()`, `search_food_stops_along_route()`, and `validate_place_open_for_window()`.

- [ ] **Step 5: Run tool tests to verify green**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv run pytest tests/test_tools.py -v`

Expected: PASS.

### Task 4: Verify And Commit

**Files:**
- All changed files from tasks above.

- [ ] **Step 1: Run all default tests**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv run pytest -v`

Expected: PASS without live API tests.

- [ ] **Step 2: Run opt-in live tests**

Run: `PICNIX_RUN_LIVE_TESTS=1 UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv run pytest tests/test_tools.py -m live -v`

Expected: PASS with configured `.env` and approved network access.

- [ ] **Step 3: Check lockfile**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv lock --check`

Expected: PASS.

- [ ] **Step 4: Commit**

Run: `git add design-context.md docs/superpowers/plans/2026-05-31-tool-layer.md pyproject.toml uv.lock tests/test_tools.py tools/gmaps.py tools/mapbox.py tools/vertex.py tools/__init__.py && git commit -m "feat: add external service tools"`
