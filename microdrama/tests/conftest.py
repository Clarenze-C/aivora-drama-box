"""Global test configuration (integrator-owned).

Session-scoped isolated PostgreSQL/Redis servers start lazily, only when a test
requests them. They bind 127.0.0.1 on free ports inside private temp dirs; see
``microdrama.testing.services``. If the binaries are missing the dependent
tests FAIL rather than silently skip — budget/locking evidence must be real.

Database fixtures:
- ``migrated_template_dsn`` (session): a database with every migration applied.
- ``db_dsn`` (function): a brand-new database cloned from that template.
- ``db`` (function): an open ``persistence.Database`` pool on ``db_dsn``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
from microdrama.persistence import Database, FilesystemObjectStore, migrate
from microdrama.testing.services import EphemeralPostgres, EphemeralRedis


@pytest.fixture(scope="session")
def pg_server_dsn() -> Iterator[str]:
    """Superuser DSN of an isolated PostgreSQL server for this test session."""
    override = os.environ.get("MICRODRAMA_TEST_DATABASE_URL")
    if override:
        yield override
        return
    server = EphemeralPostgres()
    try:
        yield server.start()
    finally:
        server.stop()


def _create_database(server_dsn: str, name: str, template: str | None = None) -> str:
    with psycopg.connect(server_dsn, autocommit=True) as conn:
        clause = f" TEMPLATE {template}" if template else ""
        conn.execute(f'CREATE DATABASE "{name}"{clause}')
    return make_conninfo(server_dsn, dbname=name)


def _drop_database(server_dsn: str, name: str) -> None:
    with psycopg.connect(server_dsn, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def migrated_template_dsn(pg_server_dsn: str) -> Iterator[str]:
    name = f"md_tpl_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    dsn = _create_database(pg_server_dsn, name)
    migrate(dsn)
    try:
        yield dsn
    finally:
        _drop_database(pg_server_dsn, name)


@pytest.fixture
def db_dsn(pg_server_dsn: str, migrated_template_dsn: str) -> Iterator[str]:
    template = psycopg.conninfo.conninfo_to_dict(migrated_template_dsn)["dbname"]
    name = f"md_t_{uuid.uuid4().hex[:12]}"
    dsn = _create_database(pg_server_dsn, name, template=f'"{template}"')
    try:
        yield dsn
    finally:
        _drop_database(pg_server_dsn, name)


@pytest.fixture
def db(db_dsn: str) -> Iterator[Database]:
    database = Database(db_dsn, min_size=1, max_size=20).open()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    override = os.environ.get("MICRODRAMA_TEST_REDIS_URL")
    if override:
        yield override
        return
    server = EphemeralRedis()
    try:
        yield server.start()
    finally:
        server.stop()


@pytest.fixture
def object_store(tmp_path) -> FilesystemObjectStore:
    return FilesystemObjectStore(tmp_path / "objects")


@pytest.fixture
def offline_settings(tmp_path) -> Settings:
    """Default OFFLINE_MOCK settings with a private temp object-store root."""
    return Settings(
        execution_mode=ExecutionMode.OFFLINE_MOCK, object_store_root=tmp_path / "objects"
    )
