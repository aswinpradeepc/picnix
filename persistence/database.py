from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config.settings import SETTINGS, Settings


POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 4

CREATE_USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    trips_planned INTEGER NOT NULL DEFAULT 0
        CHECK (trips_planned >= 0 AND trips_planned <= 5),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);
"""

CREATE_TRIP_RUNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS trip_runs (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    thread_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    count_applied BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
"""

CREATE_TRIP_RUNS_RUNNING_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS trip_runs_one_running_per_user
ON trip_runs(username)
WHERE status = 'running';
"""

PICNIX_SCHEMA_STATEMENTS = (
    CREATE_USERS_TABLE_SQL,
    CREATE_TRIP_RUNS_TABLE_SQL,
    CREATE_TRIP_RUNS_RUNNING_INDEX_SQL,
)


def create_connection_pool(settings: Settings = SETTINGS) -> ConnectionPool:
    """Create the shared psycopg connection pool used by Picnix and LangGraph."""
    return ConnectionPool(
        conninfo=settings.database_url,
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        open=True,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "prepare_threshold": 0,
        },
    )


@contextmanager
def _connection(connection_source: Any) -> Iterator[Any]:
    if hasattr(connection_source, "connection"):
        with connection_source.connection() as connection:
            yield connection
    else:
        yield connection_source


def initialize_picnix_schema(connection_source: Any) -> None:
    """Provision Picnix-owned PostgreSQL tables if they do not already exist."""
    with _connection(connection_source) as connection:
        with connection.cursor() as cursor:
            for statement in PICNIX_SCHEMA_STATEMENTS:
                cursor.execute(statement)


def create_postgres_checkpointer(connection_source: Any) -> PostgresSaver:
    """Create and initialize LangGraph's PostgreSQL checkpoint schema."""
    checkpointer = PostgresSaver(connection_source)
    checkpointer.setup()
    return checkpointer


def create_runtime_checkpointer(settings: Settings = SETTINGS) -> PostgresSaver:
    """Create the production checkpointer after provisioning all required tables."""
    pool = create_connection_pool(settings)
    try:
        initialize_picnix_schema(pool)
        return create_postgres_checkpointer(pool)
    except Exception:
        pool.close()
        raise
