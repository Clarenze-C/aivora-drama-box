"""Contract-test configuration for the editing lane (T015).

Puts the unit lane's ``editing_support`` module on ``sys.path`` (the same pattern
the references/story lanes use) and provides the World fixture so contract tests
exercise real module outputs against the frozen contracts.
"""

from __future__ import annotations

import sys
from pathlib import Path

_UNIT_SUPPORT = Path(__file__).resolve().parents[2] / "unit" / "editing"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest  # noqa: E402
from editing_support import ClipCache, World  # noqa: E402

from microdrama.persistence import Database, FilesystemObjectStore  # noqa: E402
from microdrama.testing.media import FixtureTruthRegistry  # noqa: E402


@pytest.fixture(scope="session")
def _clip_cache(tmp_path_factory) -> ClipCache:
    return ClipCache(tmp_path_factory.mktemp("editing-contract-clips"))


@pytest.fixture
def world(
    db: Database,
    object_store: FilesystemObjectStore,
    offline_settings,
    _clip_cache: ClipCache,
    fixture_truth: FixtureTruthRegistry,
) -> World:
    return World(db, object_store, offline_settings, _clip_cache, fixture_truth)
