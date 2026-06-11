# Picnix

Picnix is a Streamlit test UI and LangGraph AI layer for planning short leisure trips. It collects trip constraints, finds reachable Google Places candidates, validates destinations, and builds a round-trip route preview with optional food stops.

## Start The Project

From the repository root:

```bash
uv run streamlit run app.py
```

PostgreSQL must be reachable at `DATABASE_URL`. For the compose deployment, the `db` service provides this automatically; for local non-compose runs, start a local Postgres matching `.env.example` or set `DATABASE_URL` to your database.

Then open the local URL Streamlit prints, usually:

```text
http://localhost:8501
```

To run on a specific port:

```bash
uv run streamlit run app.py --server.port 8501
```

Stop the server with `Ctrl+C` in the terminal that is running Streamlit.

## Setup

Install `uv` and use Python 3.13 or newer.

Create a local `.env` file from the template:

```bash
cp .env.example .env
```

Fill these keys:

```text
GOOGLE_MAPS_API_KEY=
MAPBOX_TOKEN=
GOOGLE_CLOUD_PROJECT=
GOOGLE_CLOUD_LOCATION=<your-vertex-ai-region>  # e.g. us-central1; use "global" for gemini-3.1-pro-preview
GOOGLE_APPLICATION_CREDENTIALS=
LLM_RETRY_ATTEMPTS=5
LLM_RETRY_BACKOFF_MIN_SECONDS=1
LLM_RETRY_BACKOFF_MAX_SECONDS=30
RESEND_API_KEY=
RESEND_FROM_EMAIL="Picnix <onboarding@resend.dev>"
APP_BASE_URL=http://localhost:8501
```

For local Vertex AI auth, prefer Application Default Credentials and leave `GOOGLE_APPLICATION_CREDENTIALS` blank unless you are using a service account JSON:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project <GOOGLE_CLOUD_PROJECT>
```

## Observability

Phoenix tracing is available but disabled by default. The app includes the Phoenix exporter by default and the Phoenix server as an optional `uv` extra for local demos.

In one terminal, start the local Phoenix dashboard:

```bash
PHOENIX_WORKING_DIR=.phoenix uv run --extra phoenix phoenix serve
```

The dashboard opens at:

```text
http://127.0.0.1:6006
```

In `.env`, enable tracing:

```text
OBSERVABILITY_ENABLED=true
ARIZE_PRODUCT=phoenix
ARIZE_PROJECT_NAME=picnix-local
```

Then run Picnix normally. Local Phoenix accepts traces on its default OTLP collector (`localhost:4317`), so `PHOENIX_COLLECTOR_ENDPOINT` can stay blank.
If tracing is enabled before Phoenix is reachable, the app keeps running and OpenTelemetry will log exporter warnings until a collector is available.

## Docker Compose Deployment

The current deployment target is a single GCP Compute Engine VM running Docker Compose. The compose stack runs three services:

- `db` — PostgreSQL 15 with data persisted in the `postgres-data` volume.
- `phoenix` — self-hosted Phoenix UI and OTLP trace collector.
- `app` — Picnix Streamlit app, sending traces to `http://phoenix:6006/v1/traces` over the compose network.

Prepare `.env` on the VM before starting the stack:

```text
GOOGLE_MAPS_API_KEY=
MAPBOX_TOKEN=
GOOGLE_CLOUD_PROJECT=
GOOGLE_CLOUD_LOCATION=global
LLM_RETRY_ATTEMPTS=5
LLM_RETRY_BACKOFF_MIN_SECONDS=1
LLM_RETRY_BACKOFF_MAX_SECONDS=30
RESEND_API_KEY=
RESEND_FROM_EMAIL="Picnix <onboarding@resend.dev>"
APP_BASE_URL=http://<VM_EXTERNAL_IP>:8501

POSTGRES_DB=picnix
POSTGRES_USER=picnix
POSTGRES_PASSWORD=<strong database password>
LANGGRAPH_STRICT_MSGPACK=true
AUTH_COOKIE_NAME=picnix_auth
AUTH_COOKIE_KEY=<generate with: openssl rand -hex 32>
AUTH_COOKIE_EXPIRY_DAYS=30

PHOENIX_ENABLE_AUTH=true
PHOENIX_SECRET=<generate with: openssl rand -hex 32>
PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD=<strong initial password>
PHOENIX_ENABLE_STRONG_PASSWORD_POLICY=true
PHOENIX_CSRF_TRUSTED_ORIGINS=http://<VM_EXTERNAL_IP>:6006
PHOENIX_API_KEY=
```

First start Phoenix, log in, and create a system API key:

```bash
docker compose up -d phoenix
```

Open `http://<VM_EXTERNAL_IP>:6006` and log in with:

```text
Email: admin@localhost
Password: <PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD>
```

After first login, create a Phoenix system API key from settings, write it into `.env` as `PHOENIX_API_KEY`, then start the app:

```bash
docker compose up -d --build app
```

The compose file builds `DATABASE_URL` for the app from the `POSTGRES_*` values and waits for Postgres to report healthy before starting Streamlit.

The app is available at `http://<VM_EXTERNAL_IP>:8501`. The Phoenix dashboard is available at `http://<VM_EXTERNAL_IP>:6006`.

Picnix accounts are created from the Streamlit sign-up tab. Passwords are stored as bcrypt hashes in Postgres. New accounts must verify their email through Resend before graph execution is enabled. Each account can complete 5 trip plans; after that, graph execution is blocked for new planning actions.

`PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD` is only used when the persisted Phoenix volume first creates the admin account. Later password changes happen inside Phoenix.

The current compose file sets `OBSERVABILITY_CAPTURE_CONTENT=true` for debugging visibility in Phoenix. Change that value to `"false"` in `docker-compose.yml` before handling sensitive real-user traffic.

## Tests

Run the default suite:

```bash
uv run pytest
```

Live external-service smoke tests are skipped by default. To enable them:

```bash
PICNIX_RUN_LIVE_TESTS=1 uv run pytest -m live
```
