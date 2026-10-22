"""Fixtures for the Facebook adapter tests (T024).

Puts the unit publishing lane's ``publishing_support`` module on ``sys.path`` (the
sanctioned pattern from ``tests/contract/publishing/conftest.py``) so this lane can
subclass ``PublishingWorld`` without touching integrator-owned files.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_UNIT_SUPPORT = Path(__file__).resolve().parents[1]
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

from facebook_support import FacebookWorld  # noqa: E402 (needs the sys.path insert above)

from microdrama.config import Settings  # noqa: E402 (after the sys.path insert)
from microdrama.persistence import Database  # noqa: E402 (after the sys.path insert)
from microdrama.publishing.facebook.transport import FacebookScenario  # noqa: E402


@pytest.fixture
def fb_world(db: Database, tmp_path: Path, offline_settings: Settings):
    """A Facebook-world factory: the real service over the T024 adapter."""

    def make(
        *,
        operations=None,
        scenarios: tuple[FacebookScenario, ...] = (),
        enabled: bool | None = None,
    ) -> FacebookWorld:
        return FacebookWorld(
            db, tmp_path, offline_settings, operations=operations, scenarios=scenarios,
            enabled=enabled,
        )  # fmt: skip

    return make
