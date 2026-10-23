"""Fixtures for the analytics (T027) tests. Builders live in ``analytics_support``.

Puts the publishing lane's ``publishing_support`` directory on ``sys.path`` (the
sanctioned pattern) so ``AnalyticsWorld`` can subclass ``PublishingWorld``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from analytics_support import AnalyticsWorld

from microdrama.config import Settings
from microdrama.persistence import Database

_UNIT_PUBLISHING = Path(__file__).resolve().parents[1] / "publishing"
if str(_UNIT_PUBLISHING) not in sys.path:
    sys.path.insert(0, str(_UNIT_PUBLISHING))


@pytest.fixture
def world(db: Database, tmp_path: Path, offline_settings: Settings) -> AnalyticsWorld:
    return AnalyticsWorld(db, tmp_path, offline_settings)
