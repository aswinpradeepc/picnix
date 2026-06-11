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
