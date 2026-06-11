from __future__ import annotations

from contextlib import contextmanager

import pytest

from config.settings import Settings
from persistence import database


def make_settings(database_url: str = "postgresql://user:pass@db:5432/picnix") -> Settings:
    return Settings(
        google_maps_api_key="gmaps-key",
        mapbox_token="mapbox-token",
        google_cloud_project="picnix-project",
        google_cloud_location="global",
        google_application_credentials="",
        database_url=database_url,
    )


def test_create_connection_pool_uses_database_url_and_required_psycopg_options(monkeypatch) -> None:
    captured: dict = {}

    class FakeConnectionPool:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(database, "ConnectionPool", FakeConnectionPool)

    pool = database.create_connection_pool(make_settings())

    assert isinstance(pool, FakeConnectionPool)
    assert captured["conninfo"] == "postgresql://user:pass@db:5432/picnix"
    assert captured["min_size"] == database.POOL_MIN_SIZE
    assert captured["max_size"] == database.POOL_MAX_SIZE
    assert captured["open"] is True
    assert captured["kwargs"]["autocommit"] is True
    assert captured["kwargs"]["row_factory"] is database.dict_row
    assert captured["kwargs"]["prepare_threshold"] == 0


def test_initialize_picnix_schema_executes_all_schema_statements() -> None:
    executed: list[str] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def execute(self, statement: str) -> None:
            executed.append(statement)

    class FakeConnection:
        def cursor(self) -> FakeCursor:
            return FakeCursor()

    class FakePool:
        @contextmanager
        def connection(self):
            yield FakeConnection()

    database.initialize_picnix_schema(FakePool())

    assert executed == list(database.PICNIX_SCHEMA_STATEMENTS)
    assert "CREATE TABLE IF NOT EXISTS users" in executed[0]
    assert "CREATE TABLE IF NOT EXISTS trip_runs" in executed[1]
    assert "CREATE UNIQUE INDEX IF NOT EXISTS trip_runs_one_running_per_user" in executed[2]


def test_load_auth_credentials_shapes_rows_for_streamlit_authenticator() -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def execute(self, *_args) -> None:
            return None

        def fetchall(self) -> list[dict]:
            return [
                {
                    "username": "alice",
                    "email": "alice@example.com",
                    "password_hash": "$2b$hash",
                }
            ]

    class FakeConnection:
        def cursor(self) -> FakeCursor:
            return FakeCursor()

    credentials = database.load_auth_credentials(FakeConnection())

    assert credentials == {
        "usernames": {
            "alice": {
                "email": "alice@example.com",
                "name": "alice",
                "password": "$2b$hash",
                "roles": ["user"],
            }
        }
    }


def test_create_user_normalizes_username_and_email() -> None:
    calls: list[tuple] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def execute(self, _statement: str, params: tuple) -> None:
            calls.append(params)

        def fetchone(self) -> dict:
            return {"username": "alice"}

    class FakeConnection:
        def cursor(self) -> FakeCursor:
            return FakeCursor()

    created = database.create_user(
        FakeConnection(),
        username=" Alice ",
        email=" Alice@Example.COM ",
        password_hash="$2b$hash",
    )

    assert created is True
    assert calls == [("alice", "alice@example.com", "$2b$hash")]


def test_create_user_returns_false_on_conflict() -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def execute(self, *_args) -> None:
            return None

        def fetchone(self) -> None:
            return None

    class FakeConnection:
        def cursor(self) -> FakeCursor:
            return FakeCursor()

    assert database.create_user(
        FakeConnection(),
        username="alice",
        email="alice@example.com",
        password_hash="$2b$hash",
    ) is False


def test_get_trips_planned_returns_persisted_counter_and_limit_for_missing_user() -> None:
    class FakeCursor:
        def __init__(self, row):
            self.row = row

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def execute(self, *_args) -> None:
            return None

        def fetchone(self):
            return self.row

    class FakeConnection:
        def __init__(self, row):
            self.row = row

        def cursor(self) -> FakeCursor:
            return FakeCursor(self.row)

    assert database.get_trips_planned(
        FakeConnection(
            {
                "username": "alice",
                "email": "alice@example.com",
                "password_hash": "$2b$hash",
                "trips_planned": 4,
            }
        ),
        "alice",
    ) == 4
    assert database.has_trial_capacity(
        FakeConnection(
            {
                "username": "alice",
                "email": "alice@example.com",
                "password_hash": "$2b$hash",
                "trips_planned": 4,
            }
        ),
        "alice",
    )
    assert not database.has_trial_capacity(FakeConnection(None), "missing")


def test_create_postgres_checkpointer_runs_langgraph_setup(monkeypatch) -> None:
    calls: list[object] = []
    source = object()

    class FakePostgresSaver:
        def __init__(self, connection_source) -> None:
            calls.append(connection_source)

        def setup(self) -> None:
            calls.append("setup")

    monkeypatch.setattr(database, "PostgresSaver", FakePostgresSaver)

    checkpointer = database.create_postgres_checkpointer(source)

    assert isinstance(checkpointer, FakePostgresSaver)
    assert calls == [source, "setup"]


def test_mark_trip_completed_increments_once_for_new_thread() -> None:
    calls: list[tuple[str, tuple | None]] = []

    class FakeTransaction:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

    class FakeCursor:
        fetches = [
            {"count_applied": False},
            {"trips_planned": 1},
        ]

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def execute(self, statement: str, params: tuple | None = None) -> None:
            calls.append((statement, params))

        def fetchone(self):
            if not self.fetches:
                return None
            return self.fetches.pop(0)

    class FakeConnection:
        def transaction(self) -> FakeTransaction:
            return FakeTransaction()

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    counted = database.mark_trip_completed(
        FakeConnection(),
        username="Alice",
        thread_id="thread-1",
    )

    assert counted is True
    assert calls[0][1] == ("alice", "thread-1")
    assert calls[1][1] == ("alice", database.TRIAL_LIMIT)
    assert calls[2][1] == ("alice", "thread-1")


def test_mark_trip_completed_does_not_double_count_existing_counted_thread() -> None:
    calls: list[str] = []

    class FakeTransaction:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

    class FakeCursor:
        fetches = [
            None,
            {"count_applied": True},
        ]

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def execute(self, statement: str, _params: tuple | None = None) -> None:
            calls.append(statement)

        def fetchone(self):
            if not self.fetches:
                return None
            return self.fetches.pop(0)

    class FakeConnection:
        def transaction(self) -> FakeTransaction:
            return FakeTransaction()

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    counted = database.mark_trip_completed(
        FakeConnection(),
        username="alice",
        thread_id="thread-1",
    )

    assert counted is False
    assert len(calls) == 2


def test_create_runtime_checkpointer_initializes_schema_then_checkpointer(monkeypatch) -> None:
    calls = []
    pool = object()
    checkpointer = object()

    monkeypatch.setattr(database, "create_connection_pool", lambda settings: pool)
    monkeypatch.setattr(
        database,
        "initialize_picnix_schema",
        lambda connection_source: calls.append(("schema", connection_source)),
    )
    monkeypatch.setattr(
        database,
        "create_postgres_checkpointer",
        lambda connection_source: (
            calls.append(("checkpointer", connection_source)) or checkpointer
        ),
    )

    result = database.create_runtime_checkpointer(make_settings())

    assert result is checkpointer
    assert calls == [("schema", pool), ("checkpointer", pool)]


def test_create_runtime_checkpointer_closes_pool_on_initialization_failure(monkeypatch) -> None:
    class FakePool:
        closed = False

        def close(self) -> None:
            self.closed = True

    pool = FakePool()

    def raise_schema_error(connection_source) -> None:
        raise RuntimeError("schema failed")

    monkeypatch.setattr(database, "create_connection_pool", lambda settings: pool)
    monkeypatch.setattr(database, "initialize_picnix_schema", raise_schema_error)

    with pytest.raises(RuntimeError, match="schema failed"):
        database.create_runtime_checkpointer(make_settings())

    assert pool.closed is True
