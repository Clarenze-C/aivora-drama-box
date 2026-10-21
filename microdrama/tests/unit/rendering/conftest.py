"""Fixtures for the rendering (T012) tests. Builders live in ``rendering_support``."""

from __future__ import annotations

import pytest
from rendering_support import RenderWorld

from microdrama.persistence import Database


@pytest.fixture
def world(db: Database) -> RenderWorld:
    return RenderWorld(db)
