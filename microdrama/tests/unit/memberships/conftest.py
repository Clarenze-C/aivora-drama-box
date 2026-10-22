"""Fixtures for the membership lane (T026) tests.

Puts this lane's ``membership_support`` directory on ``sys.path`` (the sanctioned
pattern from ``tests/contract/publishing/conftest.py``) so test modules import
``MembershipWorld`` without touching other lanes' scaffolding.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from microdrama.config import Settings
from microdrama.persistence import Database

_LANE = Path(__file__).resolve().parent
if str(_LANE) not in sys.path:
    sys.path.insert(0, str(_LANE))


@pytest.fixture
def world(db: Database, tmp_path: Path, offline_settings: Settings):
    from membership_support import MembershipWorld

    return MembershipWorld(db, tmp_path, offline_settings)
