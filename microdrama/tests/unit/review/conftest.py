"""Fixtures for the review tests (T008): deterministic clock/ids, the real database, one service."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from review_support import World

from microdrama.persistence import Database, FilesystemObjectStore
from microdrama.testing.fakes import FakeClock, SequentialIds


@pytest.fixture
def clock() -> FakeClock:
    """Anchored at the real instant: approvals are judged by the database's server clock."""
    return FakeClock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def ids() -> SequentialIds:
    return SequentialIds("review-tests")


@pytest.fixture
def world(
    db: Database,
    clock: FakeClock,
    ids: SequentialIds,
    object_store: FilesystemObjectStore,
    offline_settings,
) -> World:
    return World(db, object_store, clock, ids, offline_settings)
