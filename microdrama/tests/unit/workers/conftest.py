"""Fixtures for the workers (T028) tests. Builders live in ``workers_support``."""

from __future__ import annotations

from pathlib import Path

import pytest
from workers_support import WorkersWorld

from microdrama.config import Settings
from microdrama.persistence import Database


@pytest.fixture
def world(db: Database, tmp_path: Path, offline_settings: Settings) -> WorkersWorld:
    return WorkersWorld(db, tmp_path, offline_settings)
