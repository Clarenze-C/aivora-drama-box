"""Fixtures for the Instagram lane (T023) tests. Builders live in ``support``.

``support`` is loaded from its file under the unique module name
``instagram_lane_support`` so a shared pytest process can never resolve another
adapter lane's support module by accident.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from publishing_support import T0

from microdrama.config import Settings
from microdrama.persistence import Database
from microdrama.publishing.instagram import InstagramAdapter
from microdrama.publishing.instagram.transport import FixtureInstagramTransport
from microdrama.testing.fakes.common import FakeClock, SequentialIds

_HERE = Path(__file__).resolve().parent
_MODULE_NAME = "instagram_lane_support"
if _MODULE_NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_MODULE_NAME, _HERE / "support.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_NAME] = _module
    assert _spec.loader is not None
    _spec.loader.exec_module(_module)

from instagram_lane_support import (  # noqa: E402
    InstagramWorld,
    default_accounts,
    write_media,
)


@pytest.fixture
def transport() -> FixtureInstagramTransport:
    """The fixture transport with both account truths registered (professional + personal)."""
    return FixtureInstagramTransport(
        clock=FakeClock(T0), ids=SequentialIds("instagram-ig"), accounts=default_accounts()
    )


@pytest.fixture
def adapter(transport: FixtureInstagramTransport) -> InstagramAdapter:
    return InstagramAdapter(transport)


@pytest.fixture
def media(tmp_path: Path) -> tuple[Path, str]:
    return write_media(tmp_path)


@pytest.fixture
def world(db: Database, tmp_path: Path, offline_settings: Settings) -> InstagramWorld:
    return InstagramWorld(db, tmp_path, offline_settings)
