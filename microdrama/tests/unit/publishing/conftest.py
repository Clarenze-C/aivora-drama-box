"""Fixtures for the publishing (T020) tests. Builders live in ``publishing_support``."""

from __future__ import annotations

from pathlib import Path

import pytest
from publishing_support import PublishingWorld

from microdrama.config import Settings
from microdrama.persistence import Database


@pytest.fixture
def world(db: Database, tmp_path: Path, offline_settings: Settings) -> PublishingWorld:
    return PublishingWorld(db, tmp_path, offline_settings)
