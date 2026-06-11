# ADR-009: Phoenix-First Observability

**Status:** Accepted
**Date:** 2026-06-11

## Context

Picnix is moving from a local AI MVP toward a product build under a strict seven-hour build/deploy window. The immediate observability goal is fast visibility into the LangGraph execution path and LLM calls, not a full production monitoring program.

The current runtime is a Streamlit app that drives a compiled LangGraph thread with `interrupt_before=["n4_route", "n8_editor"]`. LLM calls go through LangChain's `ChatGoogleGenerativeAI`; external map/routing calls remain plain Python helpers in `tools/gmaps.py`.

## Decision

Use **Phoenix** as the primary observability target for this milestone, configured through `ARIZE_PRODUCT=phoenix`.

Instrumentation is intentionally global and thin:

- `app.py` calls `configure_observability()` before importing `graph.graph`, so OpenInference instrumentation is installed before LangGraph/LangChain runtime imports.
- `observability/bootstrap.py` uses `phoenix.otel.register(...)` and `openinference.instrumentation.langchain.LangChainInstrumentor`.
- Phoenix registration uses batch export so a missing collector logs exporter warnings but does not block graph execution.
- `OBSERVABILITY_ENABLED=false` by default.
- `OBSERVABILITY_CAPTURE_CONTENT=false` by default, hiding prompts, user inputs, and model outputs from traces unless explicitly enabled for local debugging.
- The verified Docker Compose deployment currently overrides content capture to `true` for debugging visibility in this milestone; change it back to `false` before real-user traffic.
- Manual node spans and manual Google Maps spans are deferred.
- The Phoenix server package is available as an optional local extra: `uv run --extra phoenix phoenix serve`.
- The GCP deployment path is a single Compute Engine VM running Docker Compose with two services: `app` and `phoenix`.
- The app sends traces to the Phoenix container at `http://phoenix:6006/v1/traces`.
- Phoenix dashboard authentication is enabled through `.env` in production (`PHOENIX_ENABLE_AUTH`, `PHOENIX_SECRET`, `PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD`), and the app uses `PHOENIX_API_KEY` for trace ingestion once a Phoenix system API key is created.

Arize AX is not implemented in this milestone. It is tracked in `docs/future-scope.md` for a later production-monitoring phase.

## Rationale

Phoenix's LangGraph documentation states that LangGraph is supported through the LangChain instrumentor, so the same OpenInference path covers the compiled graph and LangChain model calls without custom span work. Phoenix's setup also supports local `phoenix serve` with no remote credentials, which fits the current local-first Streamlit app and short timeline.

Self-hosting Phoenix is a separate service decision, not an app runtime concern. Phoenix exposes a UI and OTLP collectors, has its own working directory/database configuration, and its official self-hosting path includes terminal, Docker/Compose, and Kubernetes options. For this milestone, Phoenix is self-hosted as its own Compose service beside the Streamlit app, not embedded in the Picnix app container.

The production deployment target is intentionally brute-force and self-contained: one GCP Compute Engine VM, Docker Compose, one Picnix app container, one Phoenix container, and a named Docker volume for Phoenix data. This avoids Cloud Run and Phoenix Cloud while still keeping the two services operationally separate.

Arize AX remains attractive for production monitoring, governance, and larger operational workflows, but implementing both Phoenix and AX now would create two backend paths before Picnix has user management, backend APIs, or deployment infrastructure.

References:

- Phoenix LangGraph tracing: https://arize.com/docs/phoenix/integrations/python/langgraph/langgraph-tracing
- Phoenix LangChain tracing: https://arize.com/docs/phoenix/integrations/python/langchain/langchain-tracing
- Phoenix environments: https://arize.com/docs/phoenix/environments
- Phoenix self-hosting: https://arize.com/docs/phoenix/self-hosting
- Phoenix configuration: https://arize.com/docs/phoenix/self-hosting/configuration
- Phoenix authentication: https://arize.com/docs/phoenix/self-hosting/features/authentication

## Consequences

- The app can be run without observability credentials; tracing is opt-in.
- Local tracing path: run `PHOENIX_WORKING_DIR=.phoenix uv run --extra phoenix phoenix serve`, set `OBSERVABILITY_ENABLED=true`, keep `ARIZE_PRODUCT=phoenix`, then run Streamlit.
- GCP deployment path: run `docker compose up` on a Compute Engine VM. Phoenix serves the dashboard on port 6006 and accepts traces from the app over the internal compose network.
- If Phoenix auth is enabled, trace ingestion requires a Phoenix system API key in `PHOENIX_API_KEY`; that key must be created from the Phoenix UI after the first admin login.
- We should expect broad LangGraph/LangChain spans quickly, but not precise per-Google-Maps-request spans until manual instrumentation is scheduled.
- Since trace content capture is off by default, initial traces favor timing/control-flow visibility over prompt debugging.

## Deferred

- Manual spans for N1-N8 and `tools/gmaps.py`.
- Explicit trace attributes for `thread_id`, selected stop count, validation failures, route duration, and edit outcomes.
- Arize AX backend support, dashboards, and production monitoring workflows.
