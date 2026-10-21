"""Fixtures for the story tests (T010): real database, deterministic clock/ids, fakes.

The root conftest supplies ``db`` (isolated PostgreSQL with every migration applied),
``offline_settings`` and the autouse offline network guard; this file only wires the lane's
``World``.
"""

from __future__ import annotations

import pytest
from story_support import World

from microdrama.config import Settings
from microdrama.persistence import Database


@pytest.fixture
def world(db: Database, offline_settings: Settings) -> World:
    return World(db, offline_settings)
