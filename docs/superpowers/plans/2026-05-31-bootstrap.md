# Picnix Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the Picnix project scaffold, uv-managed environment, `TripState` contract, and dotenv-based settings loader.

**Architecture:** Keep runtime code split by responsibility: `graph/` owns LangGraph state and nodes, `config/` owns environment loading, `tools/` will own external API wrappers, and `tests/` captures behavior before implementation. This bootstrap slice intentionally avoids graph nodes and Streamlit UI behavior until the state/config foundation is verified.

**Tech Stack:** Python 3.13 in this environment, uv, pytest, python-dotenv, Streamlit, LangGraph, LangChain Vertex AI integration, pydeck, requests.

---

### Task 1: Project Name And Package Management

**Files:**
- Modify: `design-context.md`
- Create: `pyproject.toml`
- Create: `uv.lock`
- Create: `.gitignore`

- [ ] **Step 1: Update project naming and dependency rules**

Replace the old project name with `Picnix`, change the project tree root to `picnix/`, replace `requirements.txt` with `pyproject.toml` and `uv.lock`, and document that dependencies are added with `uv add <package>`.

- [ ] **Step 2: Initialize uv project metadata**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv init --bare --name picnix --app --no-readme --vcs none --author-from none --python python3 --no-pin-python`

Expected: `pyproject.toml` exists with project name `picnix`.

- [ ] **Step 3: Add runtime dependencies**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv add streamlit pydeck langgraph langchain-core langchain-google-genai python-dotenv requests`

Expected: `pyproject.toml` lists runtime dependencies and `uv.lock` is generated.

- [ ] **Step 4: Add pytest as a dev dependency**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv add --dev pytest`

Expected: `pyproject.toml` contains a `dev` dependency group with `pytest`.

### Task 2: TripState Contract

**Files:**
- Create: `graph/__init__.py`
- Create: `graph/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing state tests**

Create tests that assert `graph.state.TripState` exists, uses the exact field order from `design-context.md`, and exposes the expected annotations.

- [ ] **Step 2: Run state tests to verify red**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv run pytest tests/test_state.py -v`

Expected: FAIL because `graph.state` is not implemented.

- [ ] **Step 3: Implement TripState**

Create `graph/state.py` with the full `TypedDict` and an inline comment for every field.

- [ ] **Step 4: Run state tests to verify green**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv run pytest tests/test_state.py -v`

Expected: PASS.

### Task 3: Settings Loader

**Files:**
- Create: `config/__init__.py`
- Create: `config/settings.py`
- Create: `.env.example`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write the failing settings tests**

Create tests that assert `.env.example` contains the four required key names and `load_settings()` reads a dotenv file into a typed settings object.

- [ ] **Step 2: Run settings tests to verify red**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv run pytest tests/test_settings.py -v`

Expected: FAIL because `config.settings` and `.env.example` are not implemented.

- [ ] **Step 3: Implement settings**

Create a small dataclass-based settings module that loads `.env` with `python-dotenv`, exposes named constants, and provides `missing_required_keys()` for connection checks.

- [ ] **Step 4: Run settings tests to verify green**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv run pytest tests/test_settings.py -v`

Expected: PASS.

### Task 4: Bootstrap Verification

**Files:**
- Verify all files created in this slice.

- [ ] **Step 1: Run all tests**

Run: `UV_CACHE_DIR=/tmp/uv-cache /home/devaccount/.local/bin/uv run pytest -v`

Expected: PASS.

- [ ] **Step 2: Inspect git status**

Run: `git status --short`

Expected: Shows the scaffold, tests, uv files, and design-context edit ready to commit.
