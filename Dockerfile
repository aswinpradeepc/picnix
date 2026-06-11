FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Node.js runs the Arize Phoenix MCP server used by the Trip Auditor page.
# Pre-installing @arizeai/phoenix-mcp lets npx resolve it offline at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @arizeai/phoenix-mcp@latest \
    && npm cache clean --force \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --format requirements-txt --output-file /tmp/requirements.txt \
    && uv pip install --system --no-cache --requirement /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY app.py ./
COPY email_utils.py ./
COPY .streamlit ./.streamlit
COPY config ./config
COPY docs ./docs
COPY graph ./graph
COPY observability ./observability
COPY pages ./pages
COPY persistence ./persistence
COPY tools ./tools

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
