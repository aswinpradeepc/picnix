FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --format requirements-txt --output-file /tmp/requirements.txt \
    && uv pip install --system --no-cache --requirement /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY app.py ./
COPY config ./config
COPY docs ./docs
COPY graph ./graph
COPY observability ./observability
COPY tools ./tools

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
