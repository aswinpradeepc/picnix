# ADR-011: Resend Email Verification for Streamlit Accounts

**Status:** Accepted
**Date:** 2026-06-11

## Context

Picnix now has PostgreSQL-backed Streamlit accounts and a strict 5-completed-trip trial gate. New accounts could previously log in and start graph execution immediately after registration. That leaves no proof that the account email is reachable, and GCP does not provide a native transactional email service comparable to SES or Resend.

The deployment target remains a single Docker Compose stack on a GCP Compute Engine VM. The verification flow must therefore fit inside the existing Streamlit app and PostgreSQL persistence boundary, without adding FastAPI, Cloud Tasks, a separate worker, or another database.

## Decision

Use the Resend API through the official `resend` Python SDK for account verification emails.

Add two columns to the `users` table:

```sql
is_verified BOOLEAN NOT NULL DEFAULT FALSE
verification_token UUID
```

Add a unique partial index on `verification_token` where the token is not null. New registrations create a UUID token, persist it in `users.verification_token`, keep `users.is_verified = FALSE`, and send an email containing a clickable Streamlit URL:

```text
<APP_BASE_URL>/?verify=<UUID>
```

On app startup, before the login/register screen renders, `app.py` checks `st.query_params["verify"]`. If the token is a valid UUID and matches a user, the app marks that user verified, clears the token, shows a success message, and clears query parameters. Verification links are one-use links because successful verification sets `verification_token = NULL`.

The graph gatekeeper now requires both:

1. `users.is_verified = TRUE`
2. `users.trips_planned < 5`

Existing users are handled in the idempotent migration by setting `is_verified = TRUE` only when the column is first introduced, so current accounts are not unexpectedly locked out.

## Configuration

The app reads these values through `config/settings.py`:

```text
RESEND_API_KEY=
RESEND_FROM_EMAIL="Picnix <onboarding@resend.dev>"
APP_BASE_URL=http://<VM_EXTERNAL_IP>:8501
```

Docker Compose passes the same environment variables into the app container. `APP_BASE_URL` must be the public Streamlit URL in deployed environments so email links point back to the VM.

## Options Considered

- **Delete all existing users during migration:** Rejected. It is operationally disruptive and unnecessary when an idempotent migration can grandfather existing accounts.
- **Use SMTP directly:** Rejected. It adds provider-specific SMTP setup and does not improve the current architecture.
- **Use a GCP-native email service:** Rejected. GCP does not provide a first-party transactional email service for this use case.
- **Add FastAPI verification endpoints:** Rejected for this milestone. Streamlit can consume the verification query parameter directly.
- **Resend SDK from Streamlit:** Chosen. It is small, explicit, and fits the existing single-app deployment.

## Consequences

- New accounts can log in but cannot run LangGraph planning until verified.
- Email delivery failures leave the account unverified; the user-facing warning says planning remains disabled until verification succeeds.
- Resend sender/domain configuration becomes a deployment concern outside the app code.
- `persistence/database.py` owns the schema migration and verification token helpers.
- `email_utils.py` is the only module that calls the Resend SDK.
