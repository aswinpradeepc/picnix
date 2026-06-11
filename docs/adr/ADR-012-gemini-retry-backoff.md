# ADR-012: Gemini Rate-Limit Retries with Tenacity

**Status:** Accepted
**Date:** 2026-06-11

## Context

Gemini calls through `ChatGoogleGenerativeAI` can fail transiently with quota and rate-limit errors, especially `429 RESOURCE_EXHAUSTED`. Picnix uses Gemini in several graph nodes: N1 intent collection, N4 dwell-time selection, N5 semantic validation, N6 itinerary composition, and N8 plan editing. Decorating each node independently would duplicate retry policy and risk inconsistent behavior.

The current model factory is centralized in `tools/vertex.py` through `get_chat_model()`, which already supplies Vertex AI project, location, model name, temperature, and structured-output options.

## Decision

Use `tenacity` to retry transient Gemini quota/rate-limit failures in the central model wrapper.

`get_chat_model()` now returns `RetryingChatGoogleGenerativeAI`, a subclass of `ChatGoogleGenerativeAI` that wraps `.invoke(...)` with a Tenacity retryer. This preserves existing node call sites and keeps `isinstance(model, ChatGoogleGenerativeAI)` true for tests and local expectations.

Retry policy:

- retry only retryable Gemini/Google quota markers such as `429`, `RESOURCE_EXHAUSTED`, `TooManyRequests`, rate-limit, or quota errors
- use capped exponential backoff with jitter via `wait_random_exponential`
- re-raise the original exception after attempts are exhausted
- log model name, retryable exception type, attempt number, and next sleep time without logging prompts or model outputs

Configuration is read from `config/settings.py`:

```text
LLM_RETRY_ATTEMPTS=5
LLM_RETRY_BACKOFF_MIN_SECONDS=1
LLM_RETRY_BACKOFF_MAX_SECONDS=30
```

## Options Considered

- **Leave failures to surface immediately:** Rejected. Transient `429 RESOURCE_EXHAUSTED` failures are common enough to hurt normal use.
- **Add retries in every node:** Rejected. It scatters policy and makes future model changes harder.
- **Use provider-specific retry options only:** Rejected. The LangChain/Google stack can surface errors through different exception classes and messages; the application needs one explicit policy.
- **Central Tenacity wrapper:** Chosen. It keeps node code unchanged and makes retry behavior testable.

## Consequences

- Transient quota/rate-limit errors are smoothed without hiding permanent schema, parsing, or auth failures.
- LLM calls can take longer under load because backoff waits happen inside graph execution.
- The retry wrapper must stay prompt-safe in logs.
- If a node has its own fallback behavior, the fallback only runs after the central retry policy is exhausted.
