"""Fixtures for the QA lane tests (T017): real DB/store, T007 media, one QAWorld."""

from __future__ import annotations

import pytest
from qa_support import QAWorld

from microdrama.persistence import Database, FilesystemObjectStore
from microdrama.testing.media import FixtureTruthRegistry


@pytest.fixture
def qa_world(
    db: Database,
    object_store: FilesystemObjectStore,
    offline_settings,
    fixture_truth: FixtureTruthRegistry,
) -> QAWorld:
    return QAWorld(db, object_store, offline_settings, fixture_truth)
