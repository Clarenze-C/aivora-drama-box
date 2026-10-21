"""Contract-test configuration for the QA lane (T017).

Puts the unit lane's ``qa_support`` module on ``sys.path`` (the same pattern the
references/editing lanes use) so contract tests exercise real module outputs against
the frozen contracts without duplicating the World scaffolding.
"""

from __future__ import annotations

import sys
from pathlib import Path

_UNIT_SUPPORT = Path(__file__).resolve().parents[2] / "unit" / "qa"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest  # noqa: E402
from qa_support import QAWorld  # noqa: E402

from microdrama.persistence import Database, FilesystemObjectStore  # noqa: E402
from microdrama.testing.media import FixtureTruthRegistry  # noqa: E402


@pytest.fixture
def qa_world(
    db: Database,
    object_store: FilesystemObjectStore,
    offline_settings,
    fixture_truth: FixtureTruthRegistry,
) -> QAWorld:
    return QAWorld(db, object_store, offline_settings, fixture_truth)
