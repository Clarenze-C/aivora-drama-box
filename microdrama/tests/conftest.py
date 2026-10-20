"""Global test configuration (integrator-owned).

Session-scoped isolated PostgreSQL/Redis servers start lazily, only when a test
requests them. They bind 127.0.0.1 on free ports inside private temp dirs; see
``microdrama.testing.services``. If the binaries are missing the dependent
tests FAIL rather than silently skip — budget/locking evidence must be real.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from microdrama.config import Settings
from microdrama.contracts.enums import ExecutionMode
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
def offline_settings(tmp_path) -> Settings:
    """Default OFFLINE_MOCK settings with a private temp object-store root."""
    return Settings(
        execution_mode=ExecutionMode.OFFLINE_MOCK, object_store_root=tmp_path / "objects"
    )
