"""Fixtures for the community (T025) tests. Builders live in ``community_support``.

Puts the publishing lane's ``publishing_support`` directory on ``sys.path`` (the
sanctioned pattern from ``tests/contract/publishing/conftest.py``) so this lane's
``community_support`` can subclass ``PublishingWorld`` without editing it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from community_support import CommunityWorld

from microdrama.config import Settings
from microdrama.persistence import Database
from microdrama.testing.fakes.community import CommunityScenario

_UNIT_PUBLISHING = Path(__file__).resolve().parents[1] / "publishing"
if str(_UNIT_PUBLISHING) not in sys.path:
    sys.path.insert(0, str(_UNIT_PUBLISHING))


def _world(db, tmp_path, offline_settings, **kwargs):
    return CommunityWorld(db, tmp_path, offline_settings, **kwargs)


@pytest.fixture
def world(db: Database, tmp_path: Path, offline_settings: Settings) -> CommunityWorld:
    return _world(db, tmp_path, offline_settings)


@pytest.fixture
def rate_limited_world(db: Database, tmp_path: Path, offline_settings: Settings) -> CommunityWorld:
    return _world(
        db,
        tmp_path,
        offline_settings,
        scenarios=(CommunityScenario.RATE_LIMITED, CommunityScenario.RATE_LIMITED),
    )
