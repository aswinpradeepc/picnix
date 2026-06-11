from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from config.settings import SETTINGS, Settings


POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 4
TRIAL_LIMIT = 5

CREATE_USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    verification_token UUID,
    trips_planned INTEGER NOT NULL DEFAULT 0
        CHECK (trips_planned >= 0 AND trips_planned <= 5),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);
"""

ADD_USER_EMAIL_VERIFICATION_COLUMNS_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'users'
          AND column_name = 'is_verified'
    ) THEN
        ALTER TABLE users
        ADD COLUMN is_verified BOOLEAN NOT NULL DEFAULT FALSE;

        UPDATE users
        SET is_verified = TRUE,
            updated_at = now();
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'users'
          AND column_name = 'verification_token'
    ) THEN
        ALTER TABLE users
        ADD COLUMN verification_token UUID;
    END IF;
END $$;
"""

CREATE_USERS_VERIFICATION_TOKEN_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS users_verification_token_unique
ON users(verification_token)
WHERE verification_token IS NOT NULL;
"""

CREATE_TRIP_RUNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS trip_runs (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    thread_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    count_applied BOOLEAN NOT NULL DEFAULT false,
    title TEXT NOT NULL DEFAULT 'Untitled plan',
    plan_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    final_itinerary TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

ADD_TRIP_RUNS_TITLE_SQL = """
ALTER TABLE trip_runs
ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT 'Untitled plan';
"""

ADD_TRIP_RUNS_PLAN_SUMMARY_SQL = """
ALTER TABLE trip_runs
ADD COLUMN IF NOT EXISTS plan_summary JSONB NOT NULL DEFAULT '{}'::jsonb;
"""

ADD_TRIP_RUNS_FINAL_ITINERARY_SQL = """
ALTER TABLE trip_runs
ADD COLUMN IF NOT EXISTS final_itinerary TEXT NOT NULL DEFAULT '';
"""

ADD_TRIP_RUNS_UPDATED_AT_SQL = """
ALTER TABLE trip_runs
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
"""

CREATE_TRIP_RUNS_RUNNING_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS trip_runs_one_running_per_user
ON trip_runs(username)
WHERE status = 'running';
"""

CREATE_TRIP_RUNS_HISTORY_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS trip_runs_history_by_user_completed_at
ON trip_runs(username, completed_at DESC)
WHERE status = 'completed' AND count_applied = true;
"""

PICNIX_SCHEMA_STATEMENTS = (
    CREATE_USERS_TABLE_SQL,
    ADD_USER_EMAIL_VERIFICATION_COLUMNS_SQL,
    CREATE_USERS_VERIFICATION_TOKEN_INDEX_SQL,
    CREATE_TRIP_RUNS_TABLE_SQL,
    ADD_TRIP_RUNS_TITLE_SQL,
    ADD_TRIP_RUNS_PLAN_SUMMARY_SQL,
    ADD_TRIP_RUNS_FINAL_ITINERARY_SQL,
    ADD_TRIP_RUNS_UPDATED_AT_SQL,
    CREATE_TRIP_RUNS_RUNNING_INDEX_SQL,
    CREATE_TRIP_RUNS_HISTORY_INDEX_SQL,
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


@contextmanager
def _transaction(connection: Any) -> Iterator[Any]:
    if hasattr(connection, "transaction"):
        with connection.transaction():
            yield connection
    else:
        yield connection


@dataclass(frozen=True)
class UserRecord:
    username: str
    email: str
    password_hash: str
    trips_planned: int
    is_verified: bool
    verification_token: UUID | None = None


@dataclass(frozen=True)
class PlanHistoryItem:
    thread_id: str
    title: str
    plan_summary: dict[str, Any]
    completed_at: Any


def initialize_picnix_schema(connection_source: Any) -> None:
    """Provision Picnix-owned PostgreSQL tables if they do not already exist."""
    with _connection(connection_source) as connection:
        with connection.cursor() as cursor:
            for statement in PICNIX_SCHEMA_STATEMENTS:
                cursor.execute(statement)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def load_auth_credentials(connection_source: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """Load DB users in the credentials shape expected by streamlit-authenticator."""
    with _connection(connection_source) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT username, email, password_hash
                FROM users
                ORDER BY username
                """
            )
            rows = cursor.fetchall()

    return {
        "usernames": {
            row["username"]: {
                "email": row["email"],
                "name": row["username"],
                "password": row["password_hash"],
                "roles": ["user"],
            }
            for row in rows
        }
    }


def create_user(
    connection_source: Any,
    *,
    username: str,
    email: str,
    password_hash: str,
) -> bool:
    """Insert a new user account. Returns False when username or email already exists."""
    normalized_username = normalize_username(username)
    normalized_email = email.strip().lower()
    with _connection(connection_source) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (username, email, password_hash)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING username
                """,
                (normalized_username, normalized_email, password_hash),
            )
            return cursor.fetchone() is not None


def set_user_verification_token(
    connection_source: Any,
    *,
    username: str,
    verification_token: UUID,
) -> bool:
    normalized_username = normalize_username(username)
    with _connection(connection_source) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE users
                SET is_verified = FALSE,
                    verification_token = %s,
                    updated_at = now()
                WHERE username = %s
                RETURNING username
                """,
                (verification_token, normalized_username),
            )
            return cursor.fetchone() is not None


def verify_user_by_token(connection_source: Any, verification_token: UUID) -> UserRecord | None:
    with _connection(connection_source) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE users
                SET is_verified = TRUE,
                    verification_token = NULL,
                    updated_at = now()
                WHERE verification_token = %s
                RETURNING username, email, password_hash, trips_planned, is_verified, verification_token
                """,
                (verification_token,),
            )
            row = cursor.fetchone()
    return _user_record_from_row(row)


def _user_record_from_row(row: dict[str, Any] | None) -> UserRecord | None:
    if row is None:
        return None
    return UserRecord(
        username=row["username"],
        email=row["email"],
        password_hash=row["password_hash"],
        trips_planned=int(row["trips_planned"]),
        is_verified=bool(row.get("is_verified", False)),
        verification_token=row.get("verification_token"),
    )


def get_user(connection_source: Any, username: str) -> UserRecord | None:
    """Return the persisted user record for a normalized username."""
    with _connection(connection_source) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT username, email, password_hash, trips_planned, is_verified, verification_token
                FROM users
                WHERE username = %s
                """,
                (normalize_username(username),),
            )
            row = cursor.fetchone()
    return _user_record_from_row(row)


def get_trips_planned(connection_source: Any, username: str) -> int:
    user = get_user(connection_source, username)
    return user.trips_planned if user else TRIAL_LIMIT


def has_trial_capacity(
    connection_source: Any,
    username: str,
    *,
    limit: int = TRIAL_LIMIT,
) -> bool:
    return get_trips_planned(connection_source, username) < limit


def update_last_login(connection_source: Any, username: str) -> None:
    with _connection(connection_source) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE users
                SET last_login_at = now(), updated_at = now()
                WHERE username = %s
                """,
                (normalize_username(username),),
            )


def mark_trip_completed(
    connection_source: Any,
    *,
    username: str,
    thread_id: str,
    title: str = "Untitled plan",
    plan_summary: dict[str, Any] | None = None,
    final_itinerary: str = "",
    limit: int = TRIAL_LIMIT,
) -> bool:
    """Idempotently count one completed graph thread against a user's trial limit."""
    normalized_username = normalize_username(username)
    safe_title = title.strip() or "Untitled plan"
    safe_summary = plan_summary or {}
    with _connection(connection_source) as connection:
        with _transaction(connection):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO trip_runs (
                        username,
                        thread_id,
                        status,
                        completed_at,
                        title,
                        plan_summary,
                        final_itinerary,
                        updated_at
                    )
                    VALUES (%s, %s, 'completed', now(), %s, %s, %s, now())
                    ON CONFLICT (thread_id) DO NOTHING
                    RETURNING count_applied
                    """,
                    (
                        normalized_username,
                        thread_id,
                        safe_title,
                        Jsonb(safe_summary),
                        final_itinerary,
                    ),
                )
                run_row = cursor.fetchone()

                if run_row is None:
                    cursor.execute(
                        """
                        SELECT count_applied
                        FROM trip_runs
                        WHERE username = %s AND thread_id = %s
                        FOR UPDATE
                        """,
                        (normalized_username, thread_id),
                    )
                    run_row = cursor.fetchone()
                    if run_row is None:
                        return False
                    if run_row["count_applied"]:
                        cursor.execute(
                            """
                            UPDATE trip_runs
                            SET title = %s,
                                plan_summary = %s,
                                final_itinerary = %s,
                                status = 'completed',
                                completed_at = COALESCE(completed_at, now()),
                                updated_at = now()
                            WHERE username = %s AND thread_id = %s
                            """,
                            (
                                safe_title,
                                Jsonb(safe_summary),
                                final_itinerary,
                                normalized_username,
                                thread_id,
                            ),
                        )
                        return False

                cursor.execute(
                    """
                    UPDATE users
                    SET trips_planned = trips_planned + 1,
                        updated_at = now()
                    WHERE username = %s AND trips_planned < %s
                    RETURNING trips_planned
                    """,
                    (normalized_username, limit),
                )
                updated_user = cursor.fetchone()
                if updated_user is None:
                    return False

                cursor.execute(
                    """
                    UPDATE trip_runs
                    SET count_applied = true,
                        status = 'completed',
                        completed_at = COALESCE(completed_at, now()),
                        title = %s,
                        plan_summary = %s,
                        final_itinerary = %s,
                        updated_at = now()
                    WHERE username = %s AND thread_id = %s
                    """,
                    (
                        safe_title,
                        Jsonb(safe_summary),
                        final_itinerary,
                        normalized_username,
                        thread_id,
                    ),
                )
                return True


def list_plan_history(
    connection_source: Any,
    username: str,
    *,
    limit: int = 20,
) -> list[PlanHistoryItem]:
    """Return completed, counted plans for a user in newest-first order."""
    normalized_username = normalize_username(username)
    with _connection(connection_source) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT thread_id, title, plan_summary, completed_at
                FROM trip_runs
                WHERE username = %s
                  AND status = 'completed'
                  AND count_applied = true
                ORDER BY completed_at DESC NULLS LAST, id DESC
                LIMIT %s
                """,
                (normalized_username, limit),
            )
            rows = cursor.fetchall()

    return [
        PlanHistoryItem(
            thread_id=row["thread_id"],
            title=row["title"] or "Untitled plan",
            plan_summary=row["plan_summary"] or {},
            completed_at=row["completed_at"],
        )
        for row in rows
    ]


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
