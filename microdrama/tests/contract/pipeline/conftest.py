"""Fixtures for the pipeline/scheduling contract lane (T029)."""

from __future__ import annotations

import pytest

from microdrama.config import Settings
from microdrama.persistence import Database
from microdrama.pipeline.world import build_pipeline_world
from microdrama.scheduling import TriggerScheduler, default_catalog


@pytest.fixture
def world(db: Database, tmp_path, offline_settings: Settings):
    return build_pipeline_world(offline_settings, db)


@pytest.fixture
def scheduler(world) -> TriggerScheduler:
    return TriggerScheduler(world, default_catalog())
