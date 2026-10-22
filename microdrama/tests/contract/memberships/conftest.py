"""Contract-test configuration for the membership lane (T026).

Puts the unit lane's directory on ``sys.path`` so the contract tests share one
source of truth for the ``MembershipWorld`` scaffolding (the sanctioned pattern
from ``tests/contract/publishing/conftest.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from microdrama.config import Settings
from microdrama.persistence import Database

_UNIT_SUPPORT = Path(__file__).resolve().parents[2] / "unit" / "memberships"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))


@pytest.fixture
def world(db: Database, tmp_path: Path, offline_settings: Settings):
    from membership_support import MembershipWorld

    return MembershipWorld(db, tmp_path, offline_settings)
