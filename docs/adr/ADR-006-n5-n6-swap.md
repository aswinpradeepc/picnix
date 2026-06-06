# ADR-006: Validate Structured Data Before Composing Prose (N5/N6 Swap)

**Status:** Accepted
**Date:** 2026-06-06

## Context

The original design placed the itinerary composer in N5 and the claim validator in N6. N6 read the LLM-generated prose and checked it against state for hallucinations. If failures were found, N6 routed back to N5 for a rewrite, with a cap of 3 rewrites. This reactive loop was LLM-heavy (up to 4 calls: 1 compose + 3 rewrites) and validated prose text — which is harder to check reliably than structured data. The checkpoint at `docs/superpowers/checkpoints/2026-06-06-dynamic-food-availability.md` recorded the intent to swap before implementing either node.

## Decision

**Swap N5 and N6:**
- **N5 (new role): Structured output validator.** Validates N4's structured output (route, timeline, food_availability) before any prose is written. Two passes: Python rule-based structural checks, then an LLM semantic pass for issues Python cannot catch. Writes `claim_failures` with `{field, issue, severity}` entries.
- **N6 (new role): Itinerary composer with inline self-check.** Writes prose from N5-verified state using a single structured LLM call that both composes prose and audits every factual claim against its source field. Unverified claims are stripped before writing `itinerary_draft`. No separate validation node; no rewrite loop.

## Options Considered

- **Keep original order (compose then validate prose)**: Works, but the validation target is natural language, which is ambiguous. The rewrite loop costs up to 3 extra LLM calls per trip and still cannot guarantee clean output.
- **Merge into one node**: N5 validates and composes in a single node. Simpler graph, but mixes two distinct responsibilities. Harder to test validation logic independently of prose quality.
- **Swap (chosen)**: Validation runs on typed, structured data — faster, cheaper, and more reliable than prose auditing. Python checks handle structural invariants without any LLM cost. The LLM semantic pass adds one call but eliminates the rewrite loop. The composer receives clean inputs and uses structured output for inline self-auditing, removing the need for a separate hallucination-guard node.

## Consequences

- `claim_failures` is now set by N5 (structured issues) instead of N6 (prose claim failures). The shape changes from `{"claim": ..., "reason": ...}` to `{"field": ..., "issue": ..., "severity": ...}`.
- `route_attempt_count` is a new `TripState` field tracking how many times the user has been re-prompted due to N5 validation errors. It is a metric, not a hard loop cap — the loop terminates naturally when `validated_candidates` becomes empty.
- `rewrite_count` is deprecated. The prose rewrite loop is gone. The field is retained in `TripState` for schema compatibility but is not written by any node.
- `itinerary_draft` is now set by N6 (the composer), not N5.
- **N5 has a conditional edge back to N4, mediated by a user re-prompt.** When N5 finds an `"error"` severity issue, it removes the invalidated destination from `validated_candidates`, resets `presented_candidate_index` to 0, sets `user_confirmed = False`, increments `route_attempt_count`, and routes to N4. Because `interrupt_before=["n4_route"]` is always active, the graph pauses before N4 runs and Streamlit shows the user the filtered list with an explanation ("That destination couldn't be fully planned — here are the remaining options."). The user makes an explicit new choice. N5→N4 with the *same* destination is never attempted.
- **The user is never silently switched to a different destination.** `route_attempt_count > 0` tells the UI to render the re-prompt variant instead of the initial selection UI.
- When N5 finds only `"warning"` severity issues, it fixes what it can in state directly and routes to N6 with warnings as context.
- `get_chat_model()` is now used by N1, N5 (LLM semantic pass), and N6. LLM call budget per trip: N1 (1–3 turns) + N5 (1 per user-confirmed attempt, bounded by queue size, max 5) + N6 (1 compose + self-check). Each N5 call that triggers a re-prompt requires an explicit user action, so the user controls the pace of any retry cycle.
