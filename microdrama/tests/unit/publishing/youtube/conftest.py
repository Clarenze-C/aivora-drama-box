"""Fixtures for the YouTube adapter (T021) tests.

Puts the T020 lane's ``publishing_support`` directory on ``sys.path`` (the
sanctioned pattern from ``tests/contract/publishing/conftest.py``) so this
lane's ``youtube_support`` can subclass ``PublishingWorld`` without editing it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from microdrama.config import Settings
from microdrama.persistence import Database

_UNIT_PUBLISHING = Path(__file__).resolve().parents[1]
if str(_UNIT_PUBLISHING) not in sys.path:
    sys.path.insert(0, str(_UNIT_PUBLISHING))


@pytest.fixture
def world(db: Database, tmp_path: Path, offline_settings: Settings):
    from youtube_support import YouTubeWorld

    return YouTubeWorld(db, tmp_path, offline_settings)
