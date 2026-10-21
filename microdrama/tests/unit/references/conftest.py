"""Fixtures for the references tests (T011): the real database and one World."""

from __future__ import annotations

import pytest
from references_support import World

from microdrama.persistence import Database, FilesystemObjectStore


@pytest.fixture
def world(
    db: Database,
    object_store: FilesystemObjectStore,
    offline_settings,
) -> World:
    return World(db, object_store, offline_settings)
