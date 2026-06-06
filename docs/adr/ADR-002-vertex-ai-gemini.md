# ADR-002: Vertex AI + Gemini 2.5 Flash as the LLM Backend

**Status:** Accepted
**Date:** 2026-05-31

## Context

The project already uses Google Cloud for Places API and Routes API. The LLM is needed for N1 (conversation), N5 (semantic validation), and N6 (prose composition). Local development must work without a service-account JSON.

## Decision

Use `gemini-2.5-flash` accessed through `ChatGoogleGenerativeAI` from `langchain-google-genai`, routing through the Vertex AI backend. Authenticate locally with Application Default Credentials (`gcloud auth application-default login`). Region: `asia-south1` (Mumbai).

## Options Considered

- **OpenAI GPT-4o**: Strong reasoning and structured output. Requires a separate API key and billing account; takes the project outside the single-GCP-account model. No regional advantage for India traffic.
- **Anthropic Claude API**: Strong at structured output and prose. Same cross-account problem. No direct LangChain-Vertex integration.
- **Gemini via direct REST/SDK (not Vertex)**: Works, but splits authentication — `GOOGLE_MAPS_API_KEY` for geo services and a separate Gemini API key. Removes the ADC-based local dev workflow. Also loses Vertex AI's enterprise quota management.
- **Gemini via Vertex AI (chosen)**: Single GCP project handles Maps, Routes, and Vertex quota. ADC covers local dev without a JSON key file. `asia-south1` puts inference close to the Kerala user base. Flash model is fast and cost-effective for the conversational and structured-output tasks in this graph.

## Consequences

- `GOOGLE_APPLICATION_CREDENTIALS` must **not** be set unless using a service account; if set it overrides ADC and breaks local dev. Documented in `.env.example`.
- Vertex AI requires `aiplatform.googleapis.com` enabled and a quota project set (`gcloud auth application-default set-quota-project`).
- `ChatGoogleGenerativeAI` is a LangChain wrapper; if the underlying Vertex API changes its response shape, updates are isolated to `tools/vertex.py`.
- Flash is appropriate for all current nodes. If a future node needs deeper reasoning (multi-day planning, budget estimation), switching to `gemini-2.5-pro` per node is straightforward via the `get_chat_model()` helper.
