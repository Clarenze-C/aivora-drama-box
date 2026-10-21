"""Fixtures for the editing tests (T015): the real database, store, clips and truth."""

from __future__ import annotations

import pytest
from editing_support import ClipCache, World

from microdrama.persistence import Database, FilesystemObjectStore
from microdrama.testing.media import FixtureTruthRegistry


@pytest.fixture(scope="session")
def clip_cache(tmp_path_factory) -> ClipCache:
    """Fixture video clips rendered once per session (CPU-bounded test media)."""
    return ClipCache(tmp_path_factory.mktemp("editing-clips"))


@pytest.fixture
def world(
    db: Database,
    object_store: FilesystemObjectStore,
    offline_settings,
    clip_cache: ClipCache,
    fixture_truth: FixtureTruthRegistry,
) -> World:
    return World(db, object_store, offline_settings, clip_cache, fixture_truth)
