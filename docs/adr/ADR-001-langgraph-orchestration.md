# ADR-001: LangGraph as the Orchestration Framework

**Status:** Accepted
**Date:** 2026-05-31

## Context

Picnix needs a multi-step AI workflow with shared mutable state, conditional branching (e.g. short-trip vs. future multiday), a retry loop inside N3, and a human-in-the-loop pause before N4. State must persist across HTTP requests so Streamlit can resume a paused graph after the user accepts a destination.

## Decision

Use LangGraph `StateGraph` with a `MemorySaver` checkpointer. All nodes read from and write to a shared `TripState` TypedDict. The interrupt and resume pattern is implemented with `interrupt_before`.

## Options Considered

- **Raw Python + `st.session_state`**: Feasible for a linear flow, but handling the interrupt/resume pattern and conditional edges manually adds significant boilerplate and the retry loop in N3 requires explicit state threading.
- **Temporal / Prefect**: General-purpose workflow engines, not designed for LLM orchestration. Heavier operational footprint; no built-in LLM tool-call abstractions.
- **LangGraph**: Designed for stateful LLM workflows. Built-in `interrupt_before`, MemorySaver checkpointing, conditional edges, LangChain message type integration. Matches the node-by-node architecture in `docs/design-context.md` directly.

## Consequences

- `interrupt_before=["n4_route"]` gives a single well-typed place to pause and resume per thread ID — Streamlit just calls `.invoke` / `.resume`.
- `MemorySaver` keeps state in memory; fine for the current single-process Streamlit deployment. Needs to be replaced with `PostgresSaver` when multi-user persistence is added.
- The StateGraph compile step validates edge coverage, catching missing node wires at startup.
- LangGraph's opinionated state-update pattern (nodes return dicts, not mutate in place) pairs naturally with the functional graph helpers in `graph/graph.py`.
