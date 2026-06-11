# ADR-002: Vertex AI + Gemini as the LLM Backend

**Status:** Accepted
**Date:** 2026-05-31

## Context

The project already uses Google Cloud for Places API and Routes API. The LLM is needed for N1 (conversation), N4 dwell timing, N5 semantic validation, N6 prose composition, and N8 plan editing. Local development must work without a service-account JSON.

## Decision

Use Gemini models accessed through `ChatGoogleGenerativeAI` from `langchain-google-genai`, routing through the Vertex AI backend. Authenticate locally with Application Default Credentials (`gcloud auth application-default login`). The original MVP used `gemini-2.5-flash`; later amendments below define the current split between reasoning and prose models.

## Amendments

- **2026-06-10:** Reasoning slots moved to `gemini-3.1-pro-preview` on `GOOGLE_CLOUD_LOCATION=global`; N6 remains on `gemini-2.5-flash`.
- **2026-06-11:** ADR-012 adds a central Tenacity retry wrapper in `tools/vertex.py` for transient Gemini quota/rate-limit errors such as `429 RESOURCE_EXHAUSTED`.

## Options Considered

- **OpenAI GPT-4o**: Strong reasoning and structured output. Requires a separate API key and billing account; takes the project outside the single-GCP-account model. No regional advantage for India traffic.
- **Anthropic Claude API**: Strong at structured output and prose. Same cross-account problem. No direct LangChain-Vertex integration.
- **Gemini via direct REST/SDK (not Vertex)**: Works, but splits authentication — `GOOGLE_MAPS_API_KEY` for geo services and a separate Gemini API key. Removes the ADC-based local dev workflow. Also loses Vertex AI's enterprise quota management.
- **Gemini via Vertex AI (chosen)**: Single GCP project handles Maps, Routes, and Vertex quota. ADC covers local dev without a JSON key file. Flash remains fast and cost-effective for prose composition, while stronger Gemini reasoning models can be selected per node through `get_chat_model()`.

## Consequences

- `GOOGLE_APPLICATION_CREDENTIALS` must **not** be set unless using a service account; if set it overrides ADC and breaks local dev. Documented in `.env.example`.
- Vertex AI requires `aiplatform.googleapis.com` enabled and a quota project set (`gcloud auth application-default set-quota-project`).
- `ChatGoogleGenerativeAI` is a LangChain wrapper; if the underlying Vertex API changes its response shape, updates are isolated to `tools/vertex.py`.
- The current app uses `gemini-3.1-pro-preview` for reasoning slots and `gemini-2.5-flash` for N6 prose. Future model changes should stay isolated to `tools/vertex.py` constants and node-specific `get_chat_model()` calls.
