# Picnix

Picnix is a Streamlit test UI and LangGraph AI layer for planning short leisure trips in Kerala. It collects trip constraints, finds reachable Google Places candidates, validates destinations, and builds a round-trip route preview with optional food stops.

## Start The Project

From the repository root:

```bash
uv run streamlit run app.py
```

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
GOOGLE_CLOUD_LOCATION=asia-south1
GOOGLE_APPLICATION_CREDENTIALS=
```

For local Vertex AI auth, prefer Application Default Credentials and leave `GOOGLE_APPLICATION_CREDENTIALS` blank unless you are using a service account JSON:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project <GOOGLE_CLOUD_PROJECT>
```

## Tests

Run the default suite:

```bash
uv run pytest
```

Live external-service smoke tests are skipped by default. To enable them:

```bash
PICNIX_RUN_LIVE_TESTS=1 uv run pytest -m live
```